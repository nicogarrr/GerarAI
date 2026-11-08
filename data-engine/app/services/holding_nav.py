"""NAV por acción publicado por la propia empresa y descuento del precio sobre él.

Caso real (8-nov-2026, backtest point-in-time de Georgia Capital, CGEO.L): una
holding que cotiza en Londres y publica sus cuentas sin etiquetar en el NSM de
la FCA no tiene hechos IFRS, así que el motor de TIR no puede arrancar; pero
cada anuncio de resultados (RNS) trae su estado del NAV («NAV per share, GEL
175.12 … NAV per share, GBP 50.10»). Para una holding el método natural es
NAV por acción publicado + descuento del precio sobre él.

Reglas generales (nunca por emisor):
- Solo la forma de TABLA: la etiqueta («NAV per share», «Net asset value per
  share», «NAV per ordinary share»), la divisa pegada (``, GEL``, ``(GBP)``,
  ``£``, ``$``, ``€``) y el número a continuación; una frase («NAV per share
  (GEL) was down 2.7% …») no cuenta, y un número seguido de «%» tampoco.
- El documento más reciente publicado en o antes de ``today`` con una
  coincidencia manda (point-in-time: nada publicado después existe).
- Si hay varias divisas, la del precio; si ninguna coincide con la del precio,
  se da el NAV sin descuento (sin tipo de cambio citado no hay cociente).
- Cada cifra viaja con su documento, su URL, su fecha y la cita literal.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import Company
from app.models.entities import Document, DocumentChunk
from app.valuation.currency import normalize_currency

MAX_DOCUMENTS = 25
QUOTE_CHARS = 90
_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}
_LABEL = r"(?i:(?:NAV|net\s+asset\s+value(?:\s*\(NAV\))?)\s+per\s+(?:ordinary\s+)?share)"
_NUMBER = r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_TABLE_FORM = re.compile(
    _LABEL
    + r"\s*(?:,\s*|\(\s*|(?i:in)\s+)?(?P<cur>[A-Z]{3}|(?i:pence)|[£$€])\s*\)?\s*"
    + r"(?P<sym>[£$€])?"
    + _NUMBER
    + r"(?!\s*%|\d|\.\d)"
)


def extract_nav_per_share(text: str) -> list[dict[str, Any]]:
    """Todas las cifras de NAV por acción en forma de tabla, en orden de aparición."""
    out: list[dict[str, Any]] = []
    flat = re.sub(r"\s+", " ", text or "")
    for match in _TABLE_FORM.finditer(flat):
        cur = match.group("cur")
        code = _SYMBOLS.get(cur, cur.upper())
        if code == "PENCE":
            code = "GBp"
        if match.group("sym"):
            code = _SYMBOLS[match.group("sym")]
        if not re.fullmatch(r"[A-Z]{3}|GBp", code):
            continue
        value = float(match.group("num").replace(",", ""))
        if value <= 0:
            continue
        start = max(0, match.start() - QUOTE_CHARS)
        end = min(len(flat), match.end() + QUOTE_CHARS)
        out.append({"value": value, "currency": code, "quote": flat[start:end].strip()})
    return out


def _published(doc: Document) -> date | None:
    value = doc.published_at
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def latest_published_nav(
    db: Session,
    company: Company,
    *,
    price: float | None,
    price_currency: str | None,
    price_date: date | None,
    today: date,
) -> dict[str, Any] | None:
    """NAV por acción del último documento publicado (<= today) que lo trae, y su descuento."""
    docs = list(db.scalars(
        select(Document)
        .where(
            Document.company_id == company.id,
            Document.published_at.is_not(None),
            Document.retention_tombstoned_at.is_(None),
        )
        .order_by(desc(Document.published_at))
        .limit(MAX_DOCUMENTS * 4)
    ).all())
    docs = [doc for doc in docs if (_published(doc) or date.max) <= today][:MAX_DOCUMENTS]
    if not docs:
        return None
    by_id = {doc.id: doc for doc in docs}
    chunks = list(db.scalars(
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id.in_(list(by_id)),
            or_(DocumentChunk.text.ilike("%nav per%"), DocumentChunk.text.ilike("%asset value per%")),
        )
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
    ).all())
    found: dict[int, list[dict[str, Any]]] = {}
    for chunk in chunks:
        hits = extract_nav_per_share(chunk.text)
        if hits:
            found.setdefault(chunk.document_id, []).extend(hits)
    if not found:
        return None
    doc = max((by_id[doc_id] for doc_id in found), key=lambda d: (_published(d) or date.min, d.id))
    hits = found[doc.id]
    major, divisor = normalize_currency(price_currency)
    same = [hit for hit in hits if normalize_currency(hit["currency"])[0] == major] if major else []
    hit = same[0] if same else hits[0]
    nav_major_currency, nav_divisor = normalize_currency(hit["currency"])
    nav_major = hit["value"] / nav_divisor
    discount = None
    reason = None
    if price is None or price <= 0:
        reason = "no_price"
    elif not same:
        reason = "currency_mismatch"
    else:
        discount = (price / divisor) / nav_major - 1
    meta = doc.metadata_ or {}
    return {
        "nav_per_share": nav_major,
        "currency": nav_major_currency,
        "price": (price / divisor) if price and divisor else None,
        "price_currency": major,
        "price_date": price_date,
        "discount": discount,
        "discount_reason": reason,
        "formula": "descuento = precio / NAV por acción publicado − 1",
        "source": {
            "title": doc.title,
            "url": doc.source_url,
            "published": _published(doc),
            "period_end": meta.get("report_date") or meta.get("period_end"),
            "quote": hit["quote"],
        },
        "other_currencies": [
            {"value": h["value"], "currency": h["currency"]} for h in hits if h is not hit
        ][:3],
    }
