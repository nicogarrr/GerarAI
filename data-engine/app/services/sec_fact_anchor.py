"""Enlace de cada cifra presentada a su sitio exacto en el informe de la SEC (iXBRL).

Un 10-K/10-Q en iXBRL marca cada cifra con ``<ix:nonFraction name="us-gaap:…"
contextRef="…" id="…">``. El navegador abre ``<documento>.htm#<id>`` justo en esa
cifra, así que el enlace de una cifra es el documento principal del filing más el
``id`` del elemento cuyo concepto, periodo (contexto SIN dimensiones) y valor
coinciden con el hecho guardado. Determinista y sin modelo:

- :func:`contexts` lee los ``xbrli:context`` (inicio/fin o instante; con o sin segmento).
- :func:`find_anchor` busca, entre los conceptos candidatos de la métrica, el elemento
  con el periodo pedido, sin dimensiones y con el valor (escala y signo aplicados) igual
  al guardado a ±0,5 unidades de su redondeo; si hay varios (la cifra se repite en el
  texto), el primero en el documento, que es el de los estados financieros.
- :func:`source_link` da el enlace con la marca ``reported`` (cifra presentada tal
  cual) o ``derived`` con su fórmula (p. ej. 4T = año − 9M, que no tiene elemento).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

ANCHOR_VERSION = "ancla_ixbrl v1"
# Conceptos us-gaap por métrica normalizada, en el orden en que se prueban.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:SalesRevenueNet", "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax"),
    "operating_income": ("us-gaap:OperatingIncomeLoss",),
    "net_income": ("us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"),
    "eps_diluted": ("us-gaap:EarningsPerShareDiluted",),
    "operating_cash_flow": ("us-gaap:NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": ("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",),
    "cash_and_equivalents": ("us-gaap:CashAndCashEquivalentsAtCarryingValue",),
    "total_assets": ("us-gaap:Assets",),
    "total_liabilities": ("us-gaap:Liabilities",),
    "total_equity": ("us-gaap:StockholdersEquity",),
    "shares_diluted": ("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",),
}

_CTX = re.compile(r"<xbrli:context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</xbrli:context>", re.S | re.I)
_START = re.compile(r"<xbrli:startDate>\s*([\d-]+)\s*<", re.I)
_END = re.compile(r"<xbrli:endDate>\s*([\d-]+)\s*<", re.I)
_INSTANT = re.compile(r"<xbrli:instant>\s*([\d-]+)\s*<", re.I)
_NONFRACTION = re.compile(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", re.S | re.I)
_ATTR = re.compile(r"([\w:-]+)=\"([^\"]*)\"")
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Context:
    id: str
    start: date | None
    end: date
    dimensional: bool


@dataclass(frozen=True)
class Anchor:
    element_id: str
    concept: str
    context: str
    value: Decimal
    url: str


def contexts(html: str) -> dict[str, Context]:
    out: dict[str, Context] = {}
    for cid, body in _CTX.findall(html):
        end = _END.search(body) or _INSTANT.search(body)
        if end is None:
            continue
        start = _START.search(body)
        try:
            out[cid] = Context(cid, date.fromisoformat(start.group(1)) if start else None,
                               date.fromisoformat(end.group(1)),
                               "segment" in body.lower() or "scenario" in body.lower())
        except ValueError:
            continue
    return out


def _value(attrs: dict[str, str], inner: str) -> Decimal | None:
    raw = _TAG.sub("", inner).replace(",", "").replace(" ", "").strip()
    if raw in ("", "-", "—"):
        raw = "0"
    try:
        v = Decimal(raw)
    except InvalidOperation:
        return None
    scale = int(attrs.get("scale") or 0)
    v = v * (Decimal(10) ** scale)
    return -v if attrs.get("sign") == "-" else v


def find_anchor(html: str, *, concepts: tuple[str, ...], end: date, start: date | None, value: float,
                doc_url: str) -> Anchor | None:
    """El elemento iXBRL del hecho (concepto, periodo sin dimensiones y valor)."""
    ctx = contexts(html)
    wanted = {cid for cid, c in ctx.items() if not c.dimensional and c.end == end and c.start == start}
    if not wanted:
        return None
    target = Decimal(str(value))
    for concept in concepts:
        for attrs_s, inner in _NONFRACTION.findall(html):
            attrs = dict(_ATTR.findall(attrs_s))
            if attrs.get("name") != concept or attrs.get("contextRef") not in wanted or not attrs.get("id"):
                continue
            v = _value(attrs, inner)
            if v is None:
                continue
            tolerance = Decimal(10) ** max(0, int(attrs.get("scale") or 0)) / 2
            if abs(v - target) <= tolerance:
                return Anchor(attrs["id"], concept, attrs["contextRef"], v, f"{doc_url}#{attrs['id']}")
    return None


def period_bounds(period: str, *, quarter_start: date | None = None) -> tuple[date | None, date]:
    """``YYYY-MM-DD:FY|Q3`` → (inicio, fin) del contexto de duración que lo presenta."""
    end_s, kind = period.split(":", 1)
    end = date.fromisoformat(end_s)
    if quarter_start is not None:
        return quarter_start, end
    months = 12 if kind.upper() == "FY" else 3
    y, m = end.year, end.month - months
    while m <= 0:
        m += 12
        y -= 1
    from calendar import monthrange

    if end.day == monthrange(end.year, end.month)[1]:
        start = date(y, m, monthrange(y, m)[1])
        start = date.fromordinal(start.toordinal() + 1)
    else:  # ejercicios de 52/53 semanas: el inicio exacto lo da el contexto, no el calendario
        start = None
    return start, end


def source_link(*, metric: str, period: str, value: float, doc_url: str | None, html: str | None,
                derived_formula: str | None = None) -> dict[str, Any]:
    """Enlace de una cifra: ``reported`` con su ancla exacta, o ``derived`` con su fórmula."""
    if derived_formula:
        return {"calc_type": "derived", "formula": derived_formula, "url": doc_url, "anchor": None,
                "version": ANCHOR_VERSION}
    out: dict[str, Any] = {"calc_type": "reported", "url": doc_url, "anchor": None, "version": ANCHOR_VERSION}
    concepts = CONCEPTS.get(metric)
    if not (html and doc_url and concepts):
        return out
    try:
        start, end = period_bounds(period)
    except ValueError:
        return out
    found = find_anchor(html, concepts=concepts, end=end, start=start, value=value, doc_url=doc_url)
    if found is None and start is None:
        # 52/53 semanas: cualquier duración que acabe ese día y dure lo que toca
        ctx = contexts(html)
        days = 365 if period.upper().endswith("FY") else 91
        for c in ctx.values():
            if c.end == end and c.start and not c.dimensional and abs((end - c.start).days - days) <= 10:
                found = find_anchor(html, concepts=concepts, end=end, start=c.start, value=value, doc_url=doc_url)
                if found:
                    break
    if found is not None:
        out.update({"anchor": found.element_id, "url": found.url, "concept": found.concept,
                    "context": found.context})
    return out
