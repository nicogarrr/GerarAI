"""Backfill de EPS/acciones diluidas para filers por clases (Visa, BRK.B...).

La API companyfacts de la SEC excluye hechos con dimensiones, asi que estos
emisores se quedan sin eps_diluted/shares_diluted en la ingesta estandar.
Este servicio lee la instancia XBRL del ultimo 10-K y recupera los hechos de
la clase que corresponde al ticker cotizado, con la misma forma de escritura
que la ingesta SEC (period '<end>:FY', fiscal_quarter='FY', source_type='SEC',
is_reported=True) para que screener y demas consumidores los vean igual.

Reglas honestas: solo se escribe lo que el emisor declaro para la clase
preferida (config por ticker, revisada a mano); si la clase preferida no esta
y hay UNA sola clase declarada, se usa esa; si hay varias y ninguna es la
preferida, no se escribe nada. Nunca se sobrescribe un hecho existente.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, Document, FinancialFact
from app.services.connectors.sec_edgar import default_headers
from app.services.connectors.sec_xbrl_instance import (
    METRIC_TAGS,
    DimensionedFact,
    parse_instance_dimensioned_facts,
)
from app.services.source_documents import get_or_create_source_document

# Clase cuyos hechos representan al ticker cotizado. Nombre LOCAL del miembro
# (sin prefijo de namespace: cada emisor usa el suyo). Revisada a mano.
CLASS_MEMBER_PREFERENCE: dict[str, str] = {
    "V": "CommonClassAMember",
    "BRK.B": "EquivalentClassBMember",
}

# Ejes dimensionales de CLASE de acciones (no de segmento ni geografia). Un
# hecho por segmento (StatementBusinessSegmentsAxis / DomesticMember) es el
# BPA de un negocio, no el del emisor: no puede escribirse como eps_diluted
# del consolidado (FIX5-9).
CLASS_AXIS_SUFFIXES = ("ClassAxis", "ClassMemberAxis", "ClassOfStockAxis")
CLASS_MEMBER_RE = re.compile(r"Class[A-Z]Member")

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/"


@dataclass(frozen=True)
class ClassEpsResult:
    ticker: str
    facts_written: int
    member_used: str | None
    periods: tuple[str, ...]
    skipped_reason: str | None = None


def _is_class_member(axis: str, member: str, preferred: str | None) -> bool:
    """Un miembro aceptable es de CLASE: eje de clase y nombre de clase.

    El eje es lo que distingue la clase de acciones de un segmento; el nombre
    (el preferido del mapa o `Class<A-Z>Member`) evita colar miembros de otros
    ejes que casualmente acaben en `ClassAxis`.
    """
    local_axis = axis.split(":")[-1]
    if not local_axis.endswith(CLASS_AXIS_SUFFIXES):
        return False
    if preferred is not None and member == preferred:
        return True
    return bool(CLASS_MEMBER_RE.search(member))


def _class_only(fact: DimensionedFact, preferred: str | None) -> bool:
    """A class total has exactly one class axis and no other scope."""
    return len(fact.members) == 1 and _is_class_member(*fact.members[0], preferred)


def pick_member(facts: list[DimensionedFact], preferred: str | None) -> str | None:
    """Miembro dimensional a usar: el preferido si esta; si hay uno solo, ese.

    Solo miembros de CLASE son candidatos (eje `*ClassAxis`/`*ClassMemberAxis`
    y nombre de clase o preferido): un miembro de segmento nunca representa al
    emisor (FIX5-9). Con varios candidatos y sin preferido presente devuelve
    None (no se elige a ciegas: escribir la clase equivocada seria fabricar el
    ratio).
    """
    members = {
        member
        for fact in facts
        if _class_only(fact, preferred)
        for axis, member in fact.members
        if _is_class_member(axis, member, preferred)
    }
    if preferred and preferred in members:
        return preferred
    if len(members) == 1:
        return next(iter(members))
    return None


def _read_response(response) -> bytes:
    data = response.read()
    # EDGAR sirve gzip cuando el cliente lo anuncia; urllib no descomprime.
    if response.headers.get("Content-Encoding") == "gzip":
        data = gzip.decompress(data)
    return data


def _require_https(url: str) -> None:
    """Solo https: urllib abriria tambien file:// y ftp:// (lectura local / SSRF)."""
    if not url.lower().startswith("https://"):
        raise ValueError(f"URL no https rechazada: {url.split(':', 1)[0]}://")


def _fetch_json(url: str) -> dict[str, Any]:
    _require_https(url)
    request = urllib.request.Request(url, headers=default_headers())
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - https verificado arriba
        return json.loads(_read_response(response).decode("utf-8"))


def _fetch_bytes(url: str) -> bytes:
    _require_https(url)
    request = urllib.request.Request(url, headers=default_headers())
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - https verificado arriba
        return _read_response(response)


def _latest_10k_instance_url(cik: str, fetch_json: Callable[[str], dict]) -> str | None:
    submissions = fetch_json(_SUBMISSIONS_URL.format(cik=cik.zfill(10)))
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    for index, form in enumerate(forms):
        if form != "10-K":
            continue
        accession = recent["accessionNumber"][index]
        acc_nodash = accession.replace("-", "")
        index_doc = fetch_json(
            f"{_ARCHIVES_URL.format(cik_int=int(cik), acc_nodash=acc_nodash)}index.json"
        )
        for item in index_doc.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if name.endswith("_htm.xml"):
                return f"{_ARCHIVES_URL.format(cik_int=int(cik), acc_nodash=acc_nodash)}{name}"
        return None
    return None


def _get_or_create_document(db: Session, company: Company, url: str) -> Document:
    return get_or_create_source_document(
        db,
        company,
        title=f"SEC XBRL instance (class facts) - {company.ticker}",
        source_type="SEC",
        source_url=url,
        metadata={"provider": "SEC", "xbrl_instance": True},
    )


def backfill_class_based_eps(
    db: Session,
    company: Company,
    *,
    cik: str,
    fetch_json: Callable[[str], dict] = _fetch_json,
    fetch_bytes: Callable[[str], bytes] = _fetch_bytes,
) -> ClassEpsResult:
    """Escribe eps_diluted/shares_diluted del 10-K para un filer por clases.

    Idempotente: un hecho ya existente (misma metrica y periodo) no se toca.
    """
    url = _latest_10k_instance_url(cik, fetch_json)
    if url is None:
        return ClassEpsResult(company.ticker, 0, None, (), skipped_reason="sin instancia 10-K")
    facts = parse_instance_dimensioned_facts(io.BytesIO(fetch_bytes(url)))
    if not facts:
        return ClassEpsResult(company.ticker, 0, None, (), skipped_reason="sin hechos dimensionados")
    # A preferred class inside a segment/geography is not the class total.
    # Filter before member selection and tag priority, not only before writes.
    preferred = CLASS_MEMBER_PREFERENCE.get(company.ticker.upper())
    facts = [fact for fact in facts if _class_only(fact, preferred)]
    member = pick_member(facts, CLASS_MEMBER_PREFERENCE.get(company.ticker.upper()))
    if member is None:
        any_class = any(
            _is_class_member(axis, m, CLASS_MEMBER_PREFERENCE.get(company.ticker.upper()))
            for f in facts
            for axis, m in f.members
        )
        return ClassEpsResult(
            company.ticker,
            0,
            None,
            (),
            skipped_reason="varias clases sin preferida" if any_class else "sin miembros de clase",
        )
    document = _get_or_create_document(db, company, url)
    written = 0
    periods: list[str] = []
    used_tags: set[str] = set()
    # La instancia repite el mismo hecho en varias secciones (balance, notas,
    # cover) con contextos distintos: dedup en memoria por (metrica, periodo),
    # la comprobacion en BD no basta con sesiones sin autoflush.
    seen_periods: set[tuple[str, str]] = set()
    for metric, tags in METRIC_TAGS.items():
        metric_facts = [
            f for f in facts if f.tag in tags and member in f.member_names and f.end
        ]
        # Solo el tag prioritario con hechos: diluido si existe, basic si no.
        for tag in tags:
            tag_facts = [f for f in metric_facts if f.tag == tag]
            if not tag_facts:
                continue
            for fact in tag_facts:
                period = f"{fact.end.isoformat()}:FY"
                if (metric, period) in seen_periods:
                    continue
                seen_periods.add((metric, period))
                exists = db.scalar(
                    select(FinancialFact.id).where(
                        FinancialFact.company_id == company.id,
                        FinancialFact.metric == metric,
                        FinancialFact.period == period,
                        *tenant_filters(db, FinancialFact),
                    )
                )
                if exists:
                    continue
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric=metric,
                        value=fact.value,
                        unit="USD/share" if metric == "eps_diluted" else "shares",
                        period=period,
                        fiscal_year=fact.end.year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="SEC",
                        is_reported=True,
                        confidence=Decimal("0.95"),
                    )
                )
                written += 1
                used_tags.add(tag)
                if period not in periods:
                    periods.append(period)
            break
    if used_tags and document.metadata_ is not None:
        document.metadata_ = {
            **(document.metadata_ or {}),
            "class_member": member,
            "xbrl_tags": sorted(used_tags),
        }
    db.flush()
    return ClassEpsResult(company.ticker, written, member, tuple(periods))



# ---------------------------------------------------------------------------
# Saldo de acciones en circulacion por clase (dei ECSO) + suma derivada
# documentada. Filers multi-clase: la SEC no consolida las clases en
# companyfacts, asi que shares_outstanding nunca llega por la ingesta
# estandar. La suma de clases se escribe como hecho DERIVADO
# (is_reported=False, source_type="derived", confianza 0.70) con la
# procedencia por clase en metadata del Document: nunca como dato reportado.
# ---------------------------------------------------------------------------

CLASS_SHARES_FILERS: tuple[str, ...] = ("META", "GOOGL", "BRK.B", "ASTS", "V")

# Ratio de conversion de cada clase a la clase COTIZADA del ticker (acciones
# de la clase cotizada por cada accion de esa clase). Revisado a mano: sumar
# clases en bruto solo es correcto cuando todas valen lo mismo (META, GOOGL,
# ASTS: 1:1). BRK.B: una accion A se convierte en 1.500 B (estatutos de
# Berkshire desde el split de 2010, 10-K Item 5): el saldo en "equivalentes
# B" es A*1500 + B. Si el emisor declara una clase que no esta en su mapa, no
# se escribe nada (no se adivina un ratio).
CLASS_CONVERSION_TO_LISTED: dict[str, dict[str, Decimal]] = {
    "BRK.B": {
        "CommonClassAMember": Decimal(1500),
        "CommonClassBMember": Decimal(1),
    },
}

# Emisores cuyo ratio de conversion entre clases VARIA en el tiempo y no esta
# revisado: Visa (las B-1/B-2 se convierten en A a un ratio que se ajusta por
# los litigios y la C a 4:1). Sin ratio fiable, la suma bruta mentiria: no se
# escribe shares_outstanding derivado.
CLASS_RATIOS_UNREVIEWED: frozenset[str] = frozenset({"V"})


def _latest_instance_url(
    cik: str, fetch_json: Callable[[str], dict], forms: tuple[str, ...] = ("10-K", "10-Q")
) -> str | None:
    """Instancia XBRL del filing mas reciente de `forms` (10-Q incluido: la
    portada con el saldo de acciones se refresca cada trimestre)."""
    submissions = fetch_json(_SUBMISSIONS_URL.format(cik=cik.zfill(10)))
    recent = submissions.get("filings", {}).get("recent", {})
    for index, form in enumerate(recent.get("form", [])):
        if form not in forms:
            continue
        acc_nodash = recent["accessionNumber"][index].replace("-", "")
        index_doc = fetch_json(
            f"{_ARCHIVES_URL.format(cik_int=int(cik), acc_nodash=acc_nodash)}index.json"
        )
        for item in index_doc.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if name.endswith("_htm.xml"):
                return f"{_ARCHIVES_URL.format(cik_int=int(cik), acc_nodash=acc_nodash)}{name}"
        return None
    return None


@dataclass(frozen=True)
class ClassSharesResult:
    ticker: str
    written: bool
    shares_total: Decimal | None
    members: tuple[str, ...]
    as_of: str | None
    skipped_reason: str | None = None


def backfill_class_shares_outstanding(
    db: Session,
    company: Company,
    *,
    cik: str,
    fetch_json: Callable[[str], dict] = _fetch_json,
    fetch_bytes: Callable[[str], bytes] = _fetch_bytes,
) -> ClassSharesResult:
    """shares_outstanding DERIVADO (suma de clases dei ECSO) para multi-clase.

    Solo miembros en eje de CLASE (`*ClassAxis` / `*ClassMemberAxis` /
    `*ClassOfStockAxis`): un miembro de segmento nunca suma acciones del
    emisor. Por clase gana el instante mas reciente; la suma es de las
    clases presentes en ESA fecha de portada mas reciente del filing (si un
    miembro solo aparece en instantes antiguos, se usa el suyo propio y la
    fecha del hecho es la del instante mas reciente global). Idempotente:
    un shares_outstanding con el mismo periodo no se toca.
    """
    from app.services.connectors.sec_xbrl_instance import (
        parse_instance_dimensioned_ecso,
    )

    url = _latest_instance_url(cik, fetch_json)
    if url is None:
        return ClassSharesResult(company.ticker, False, None, (), None,
                                 skipped_reason="sin instancia 10-K/10-Q")
    facts = parse_instance_dimensioned_ecso(io.BytesIO(fetch_bytes(url)))
    # Solo miembros de CLASE (eje de clase): los de segmento/geografia no
    # son acciones del emisor.
    by_member: dict[str, DimensionedFact] = {}
    for fact in facts:
        class_axes = [
            (axis, member)
            for axis, member in fact.members
            if axis.split(":")[-1].endswith(CLASS_AXIS_SUFFIXES)
        ]
        if not class_axes:
            continue
        member = class_axes[0][1]
        current = by_member.get(member)
        if current is None or (fact.instant or date.min) > (current.instant or date.min):
            by_member[member] = fact
    if not by_member:
        return ClassSharesResult(company.ticker, False, None, (), None,
                                 skipped_reason="sin ECSO dimensionado por clase")
    ticker_key = (company.ticker or "").upper()
    if ticker_key in CLASS_RATIOS_UNREVIEWED:
        return ClassSharesResult(company.ticker, False, None, tuple(sorted(by_member)), None,
                                 skipped_reason="ratio de conversion entre clases sin revisar")
    ratios = CLASS_CONVERSION_TO_LISTED.get(ticker_key)
    if ratios is not None:
        unmapped = sorted(m for m in by_member if m not in ratios)
        if unmapped:
            return ClassSharesResult(
                company.ticker, False, None, tuple(sorted(by_member)), None,
                skipped_reason=f"clase sin ratio de conversion revisado: {', '.join(unmapped)}",
            )
    # Equivalentes de la clase cotizada: cada clase pesa por su ratio (1:1 si
    # el emisor no tiene mapa, p. ej. META o GOOGL).
    total = sum((
        f.value * (ratios[m] if ratios is not None else Decimal(1))
        for m, f in by_member.items()
    ), Decimal(0))
    if total <= 0:
        return ClassSharesResult(company.ticker, False, None, (), None,
                                 skipped_reason="suma de clases no positiva")
    as_of = max(f.instant for f in by_member.values() if f.instant)
    period = f"{as_of.isoformat()}:DEI"
    exists = db.scalar(
        select(FinancialFact.id).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "shares_outstanding",
            FinancialFact.period == period,
            *tenant_filters(db, FinancialFact),
        )
    )
    if exists:
        return ClassSharesResult(company.ticker, False, total,
                                 tuple(sorted(by_member)), as_of.isoformat(),
                                 skipped_reason="ya existe")
    document = _get_or_create_document(db, company, url)
    db.add(
        FinancialFact(
            company_id=company.id,
            metric="shares_outstanding",
            value=total,
            unit="shares",
            period=period,
            fiscal_year=None,
            fiscal_quarter=None,
            source_id=document.id,
            source_type="derived",
            is_reported=False,
            confidence=Decimal("0.70"),
        )
    )
    document.metadata_ = {
        **(document.metadata_ or {}),
        "class_shares_provenance": {
            "concept": "dei:EntityCommonStockSharesOutstanding",
            "derivation": (
                "sum_of_class_members" if ratios is None else "as_converted_to_listed_class"
            ),
            "as_of": as_of.isoformat(),
            "members": {m: str(f.value) for m, f in sorted(by_member.items())},
            **(
                {"conversion_ratios": {m: str(ratios[m]) for m in sorted(by_member)}}
                if ratios is not None
                else {}
            ),
        },
    }
    db.flush()
    return ClassSharesResult(company.ticker, True, total,
                             tuple(sorted(by_member)), as_of.isoformat())
