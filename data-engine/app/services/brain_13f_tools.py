"""Cerebro: «¿Qué ha hecho Buffett con Apple en su último 13F?» sin modelo.

Benchmark Cerebro 2026-11-08 (ins08): la pregunta nombra a un inversor y la
guardia de citas de autor la cortaba con «No tengo un fragmento verificable de
ese autor», aunque no pide una cita sino su 13F, que la app guarda. Regla
general: si la pregunta pide el 13F de un inversor del registro que presenta
13F, se responde con el último 13F guardado (posición y cambio frente al
trimestre anterior) y lo que falte sale como «N/D: falta X (motivo)». Toda
cifra sale del 13F guardado; ninguna se calcula aquí salvo el formato.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from app.schemas import ChatResponse

#: «13F», «13-F», «13 F», «formulario 13F», «13F-HR».
_ASKS_13F_RE = re.compile(r"(?i)(?<![\w-])13\s*-?\s*f(?:-hr)?(?![\w])")
#: Palabras de razón social que no identifican al emisor («APPLE INC» → apple).
_ISSUER_NOISE = frozenset({
    "inc", "corp", "corporation", "co", "company", "ltd", "plc", "sa", "nv", "ag", "se", "lp", "llc",
    "group", "holdings", "holding", "class", "cl", "com", "new", "del", "the", "and", "de", "a", "b", "c",
    "shs", "ord", "adr", "sponsored", "ads", "trust", "fund", "etf", "intl", "international",
})


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return plain.lower()


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _fold(text)))


def asks_13f(question: str) -> bool:
    return bool(_ASKS_13F_RE.search(question or ""))


def named_13f_investor(question: str):
    """Inversor del registro con 13F nombrado en la pregunta (apellido, nombre o firma)."""
    from app.services.investors import INVESTORS

    words = _words(question)
    found = []
    for inv in INVESTORS:
        if not inv.cik:
            continue
        name_tokens = [t for t in re.findall(r"[a-z0-9]+", _fold(inv.name)) if len(t) >= 4]
        firm_core = [t for t in re.findall(r"[a-z0-9]+", _fold(inv.firm)) if t not in _ISSUER_NOISE and len(t) >= 4]
        by_name = bool(name_tokens) and name_tokens[-1] in words
        # «Berkshire» basta para Berkshire Hathaway (el nombre propio de la firma).
        by_firm = bool(firm_core) and firm_core[0] in words
        if by_name or by_firm:
            found.append(inv)
    return found[0] if len(found) == 1 else None


def _issuer_core(issuer: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _fold(issuer)) if t not in _ISSUER_NOISE and len(t) >= 3]


def _issuer_in_question(issuer: str, words: set[str]) -> bool:
    core = _issuer_core(issuer)
    return bool(core) and core[0] in words and len(core[0]) >= 4


def _value(datum: dict | None) -> float | None:
    if not isinstance(datum, dict):
        return None
    value = datum.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _fmt_int(value: float, en: bool) -> str:
    text = f"{abs(value):,.0f}"
    return text if en else text.replace(",", ".")


def _fmt_money(value: float, en: bool) -> str:
    if en:
        return f"${value:,.0f}"
    return f"{value:,.0f}".replace(",", ".") + " USD"


def _fmt_pct(value: float, en: bool) -> str:
    text = f"{value:.2f}"
    return f"{text} %" if en else f"{text.replace('.', ',')} %"


_ACTIONS = {
    "nueva": ("posición nueva", "new position"),
    "cerrada": ("posición cerrada", "position closed"),
    "aumento": ("aumentó", "increased"),
    "reduccion": ("redujo", "reduced"),
}


def _english() -> bool:
    from app.core.i18n import current_language

    return current_language() == "en"


def _response(lines: list[str], sources: list[dict], **trace: Any) -> ChatResponse:
    return ChatResponse(
        answer="\n".join(lines), sources=sources, model="deterministic", prompt_version="brain-13f-v1",
        confidence=0.9, llm_trace={"path": "investor_13f", "provider_calls": 0, "generated": False, **trace},
    )


def answer_13f_question(db: Session, question: str) -> ChatResponse | None:
    """Respuesta con el último 13F guardado, o None si la pregunta no es de 13F de un inversor."""
    if not asks_13f(question):
        return None
    inv = named_13f_investor(question)
    if inv is None:
        return None
    from app.services.investor_portfolio import investor_portfolio

    en = _english()
    body = investor_portfolio(db, inv.slug)
    source = {"type": "investor_13f", "id": inv.slug, "title": f"13F {inv.firm}", "url": f"/investors/{inv.slug}"}
    if not body or body.get("status") != "ok":
        line = (
            f"N/D: missing {inv.firm}'s 13F in the app (reason: no 13F has been ingested for this manager yet)."
            if en
            else f"N/D: falta el 13F de {inv.firm} en la app (motivo: todavía no hay ningún 13F ingerido de este gestor)."
        )
        return _response([line], [], investor=inv.slug, status="sin_datos")
    as_of = str(body.get("as_of") or "")
    positions = body.get("positions") or []
    movements = body.get("movements") or []
    words = _words(question)
    filing_url = next(
        (p["shares"]["source_url"] for p in positions if isinstance(p.get("shares"), dict) and p["shares"].get("source_url")),
        None,
    )
    if filing_url:
        source["filing_url"] = filing_url
    head = (f"{inv.name} ({inv.firm}), 13F with quarter end {as_of}:" if en
            else f"{inv.name} ({inv.firm}), 13F con cierre de trimestre {as_of}:")
    # Emisores que nombra la pregunta (por nombre, no por ticker: el 13F no lo trae).
    asked = sorted({p["issuer"] for p in positions if _issuer_in_question(p.get("issuer") or "", words)}
                   | {m["issuer"] for m in movements if _issuer_in_question(m.get("issuer") or "", words)})
    lines = [head]
    if not asked:
        top = positions[:5]
        for p in top:
            lines.append(f"- {_position_line(p, en)}")
        if movements:
            lines.append("Changes vs the previous 13F (largest positions first):" if en
                         else "Cambios frente al 13F anterior (primero las posiciones más grandes):")
            for m in movements[:5]:
                lines.append(f"- {_movement_line(m, en)}")
        lines.append(_coverage_line(body, en))
        return _response(lines, [source], investor=inv.slug, status="ok", issuers=[])
    for issuer in asked:
        rows = [p for p in positions if p.get("issuer") == issuer]
        for p in rows:
            lines.append(f"- {_position_line(p, en)}")
        moves = [m for m in movements if m.get("issuer") == issuer]
        for m in moves:
            lines.append(f"- {_movement_line(m, en)}")
        if not moves:
            lines.append(
                f"- N/D: missing the change in {issuer} vs the previous 13F (reason: it is not among the changes the app computed)."
                if en
                else f"- N/D: falta el cambio de {issuer} frente al 13F anterior (motivo: no está entre los cambios que calcula la app)."
            )
    lines.append(_coverage_line(body, en))
    return _response(lines, [source], investor=inv.slug, status="ok", issuers=asked)


def _position_line(p: dict, en: bool) -> str:
    issuer = p.get("issuer") or "?"
    parts = [issuer + (f" ({p['title_of_class']})" if p.get("title_of_class") else "")]
    shares, value, weight = _value(p.get("shares")), _value(p.get("value_usd")), _value(p.get("weight_pct"))
    na = "N/D"
    parts.append(f"{_fmt_int(shares, en)} {'shares' if en else 'acciones'}" if shares is not None
                 else f"{'shares' if en else 'acciones'} {na}")
    parts.append(f"{'value' if en else 'valor'} {_fmt_money(value, en)}" if value is not None
                 else f"{'value' if en else 'valor'} {na}")
    if weight is not None:
        parts.append(f"{'weight' if en else 'peso'} {_fmt_pct(weight, en)}")
    text = ", ".join(parts)
    if p.get("note"):
        text += f" ({p['note']})"
    return text


def _movement_line(m: dict, en: bool) -> str:
    issuer = m.get("issuer") or "?"
    action = m.get("action") or "sin_datos"
    delta, after = _value(m.get("shares")), _value(m.get("shares_after"))
    if action not in _ACTIONS or delta is None:
        return (f"{issuer}: N/D: missing the change vs the previous 13F (reason: a share count is missing in one of the two filings)."
                if en else
                f"{issuer}: N/D: falta el cambio frente al 13F anterior (motivo: falta el número de acciones en uno de los dos 13F).")
    es_label, en_label = _ACTIONS[action]
    label = en_label if en else es_label
    text = f"{issuer}: {label}"
    if action in {"aumento", "reduccion", "nueva", "cerrada"}:
        text += f", {'+' if delta > 0 else '-' if delta < 0 else ''}{_fmt_int(delta, en)} {'shares' if en else 'acciones'}"
    if after is not None and action != "cerrada":
        text += f" ({'now' if en else 'ahora'} {_fmt_int(after, en)})"
    return text + "."


def _coverage_line(body: dict, en: bool) -> str:
    if body.get("coverage") == "ok":
        return ("Source: the 13F-HR filed with the SEC; a 13F shows quarter-end holdings, not trade dates." if en
                else "Fuente: el 13F-HR presentado en la SEC; un 13F muestra posiciones a cierre de trimestre, no fechas de compra o venta.")
    return ("Partial coverage: the 13F is not verified as complete, so weights and total are N/D." if en
            else "Cobertura parcial: el 13F no está verificado como completo; pesos y total, N/D.")
