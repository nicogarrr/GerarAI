"""Inputs de los motores sectoriales sacados del TEXTO del informe anual.

Los motores de aseguradoras y REIT necesitan cifras que el XBRL us-gaap no
etiqueta: el ratio combinado (no hay concepto us-gaap) y el NOI de un REIT
(medida no-GAAP que el 10-K concilia en el MD&A). Aqui se leen del texto del
filing ya ingerido (DocumentChunk) con reglas deterministas sobre la fila de
la tabla, y se guardan como ``FinancialFact`` NO reportado:

- ``source_type="document_extract"``, ``is_reported=False``: nunca pasa por
  dato oficial; el motor lo etiqueta «extraído del 10-K (inferido)».
- ``source_id`` = el filing; su ``metadata["sector_extracts"][metrica]``
  guarda metodo, cita literal, escala y el cotejo con otras fuentes.
- Cotejo: si otro filing ya dio la misma metrica y ejercicio con otro valor
  (>1 %), gana el filing mas reciente y la discrepancia queda anotada en los
  dos sentidos. Una sola fuente queda dicha («una sola fuente oficial»).

Sin cita localizable, sin escala declarada («in thousands/millions») o fuera
de rango no se escribe nada: el input sigue ausente.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Document, FinancialFact
from app.models.entities import DocumentChunk

EXTRACT_SOURCE_TYPE = "document_extract"
ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"})
SINGLE_SOURCE_NOTE = "una sola fuente oficial (el informe anual); sin segunda fuente para cotejar"
AGREE_TOLERANCE = 0.01
MAX_CHARS = 3_000_000

_NUM = r"\(?\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*\)?"
_COMBINED = re.compile(
    r"(?P<prefix>P&C|P&amp;C|consolidated|total|overall)?\s*combined\s+ratio\s*(?:\(\d\))?\s*"
    r"(?P<a>\d{2,3}(?:\.\d+)?)\s*%(?:\s*(?P<b>\d{2,3}(?:\.\d+)?)\s*%)?(?:\s*(?P<c>\d{2,3}(?:\.\d+)?)\s*%)?",
    re.IGNORECASE,
)
_NOI = re.compile(
    r"(?<![A-Za-z])(?:total\s+)?(?:property\s+)?net\s+operating\s+income\s*(?:\(\s*\"?NOI\"?\s*\))?\s*"
    r"\$\s*(?P<a>\d{1,3}(?:,\d{3})+)\s*(?:\$\s*(?P<b>\d{1,3}(?:,\d{3})+))?",
    re.IGNORECASE,
)
_YEARS = re.compile(r"\b(20\d\d)\s+(20\d\d)\b")
_SCALE = re.compile(r"in\s+(thousands|millions|billions)", re.IGNORECASE)
_SCALES = {"thousands": 1_000, "millions": 1_000_000, "billions": 1_000_000_000}


def _form(document: Document) -> str:
    return str((document.metadata_ or {}).get("form") or "").upper()


def fiscal_year_of(document: Document) -> int | None:
    """Ejercicio del informe anual: report_date del indice o, si falta, el
    año anterior a la presentacion (los 10-K se presentan en ene-abr)."""
    meta = document.metadata_ or {}
    for key in ("report_date", "period_of_report"):
        raw = str(meta.get(key) or "")
        if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return int(raw[:4])
    published = document.published_at
    if isinstance(published, datetime):
        return published.year - 1 if published.month <= 6 else published.year
    return None


def _ascending_years_before(text: str, pos: int) -> bool:
    """True si la cabecera de columnas mas cercana va de antiguo a reciente."""
    window = text[max(0, pos - 800) : pos]
    found = _YEARS.findall(window)
    if not found:
        return False
    first, second = found[-1]
    return int(first) < int(second)


def _row_latest(match: re.Match, text: str) -> str:
    values = [match.group(g) for g in ("a", "b", "c") if match.groupdict().get(g)]
    if len(values) > 1 and _ascending_years_before(text, match.start()):
        return values[-1]
    return values[0]


def _quote(text: str, match: re.Match) -> str:
    return re.sub(r"\s+", " ", text[max(0, match.start() - 60) : match.end() + 20]).strip()[:300]


def extract_combined_ratio(text: str) -> dict[str, Any] | None:
    """Ratio combinado consolidado (fraccion) de la fila de su tabla.

    Prefiere la fila con prefijo de agregado (P&C / consolidated / total);
    sin prefijo solo vale si todas las filas sin prefijo coinciden (si no,
    son segmentos y no hay una cifra de la compañia).
    """
    matches = list(_COMBINED.finditer(text))
    if not matches:
        return None
    prefixed = [m for m in matches if m.group("prefix")]
    if prefixed:
        chosen = prefixed[0]
    else:
        values = {_row_latest(m, text) for m in matches}
        if len(values) != 1:
            return None
        chosen = matches[0]
    pct = float(_row_latest(chosen, text))
    if not 50.0 <= pct <= 150.0:
        return None
    return {
        "value": pct / 100.0,
        "unit": "ratio",
        "method": "fila «combined ratio» de la tabla del MD&A del informe anual (ultimo ejercicio)",
        "quote": _quote(text, chosen),
    }


def extract_noi(text: str) -> dict[str, Any] | None:
    """NOI del ejercicio de la conciliacion del MD&A, con su escala declarada."""
    for match in _NOI.finditer(text):
        raw = _row_latest(match, text)
        scale_hits = _SCALE.findall(text[max(0, match.start() - 6000) : match.start()])
        if not scale_hits:
            continue
        scale = _SCALES[scale_hits[-1].lower()]
        value = float(raw.replace(",", "")) * scale
        if value <= 0:
            continue
        return {
            "value": value,
            "unit": None,
            "method": f"conciliacion de NOI del MD&A del informe anual (cifra en {scale_hits[-1].lower()})",
            "quote": _quote(text, match),
        }
    return None


EXTRACTORS = {
    "insurer": (("combined_ratio", extract_combined_ratio),),
    "reit": (("net_operating_income", extract_noi),),
}


def _document_text(db: Session, document: Document) -> str:
    chunks = db.scalars(
        select(DocumentChunk.text)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    return re.sub(r"\s+", " ", " ".join(chunks))[:MAX_CHARS]


def _plausible(db: Session, company: Company, metric: str, value: float, year: int) -> bool:
    if metric != "net_operating_income":
        return True
    revenue = db.scalar(
        select(FinancialFact.value)
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue",
            FinancialFact.fiscal_year == year,
            FinancialFact.is_reported.is_(True),
        )
        .order_by(FinancialFact.id.desc())
        .limit(1)
    )
    # El NOI es una parte de los ingresos de explotacion: mayor que ellos es
    # una escala mal leida (miles tomados por millones).
    return revenue is None or 0 < value <= float(revenue) * 1.05


def extract_from_document(db: Session, document: Document) -> dict[str, Any]:
    """Extrae y guarda los inputs sectoriales de un informe anual ingerido."""
    from app.valuation.engines.registry import resolve_engine_key

    if _form(document) not in ANNUAL_FORMS or document.company_id is None:
        return {"status": "not_applicable"}
    company = db.get(Company, document.company_id)
    if company is None:
        return {"status": "not_applicable"}
    extractors = EXTRACTORS.get(resolve_engine_key(company))
    if not extractors:
        return {"status": "not_applicable"}
    year = fiscal_year_of(document)
    if year is None:
        return {"status": "skipped", "reason": "sin ejercicio del informe"}
    text = _document_text(db, document)
    written: dict[str, Any] = {}
    meta_extracts = dict((document.metadata_ or {}).get("sector_extracts") or {})
    for metric, extractor in extractors:
        found = extractor(text)
        if found is None or not _plausible(db, company, metric, found["value"], year):
            written[metric] = None
            continue
        others = db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == metric,
                FinancialFact.fiscal_year == year,
                FinancialFact.source_type == EXTRACT_SOURCE_TYPE,
                FinancialFact.source_id != document.id,
            )
        ).all()
        disagreeing = [
            o
            for o in others
            if abs(float(o.value) - found["value"]) > AGREE_TOLERANCE * max(abs(found["value"]), 1e-9)
        ]
        if others and not disagreeing:
            note = f"coincide con {len(others)} fuente(s) oficial(es) mas"
        elif disagreeing:
            note = (
                "discrepancia con otra fuente ("
                + ", ".join(f"{float(o.value):.4g}" for o in disagreeing)
                + "): manda el filing mas reciente"
            )
        else:
            note = SINGLE_SOURCE_NOTE
        existing = db.scalar(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == metric,
                FinancialFact.fiscal_year == year,
                FinancialFact.source_id == document.id,
            )
        )
        unit = found["unit"] or (company.currency or "USD")
        if existing is None:
            existing = FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(found["value"])),
                unit=unit,
                period=f"FY{year}",
                fiscal_year=year,
                fiscal_quarter="FY",
                source_id=document.id,
                source_type=EXTRACT_SOURCE_TYPE,
                is_reported=False,
                is_adjusted=False,
                confidence=Decimal("0.70") if note == SINGLE_SOURCE_NOTE else Decimal("0.80"),
                accession_number=(document.metadata_ or {}).get("accession_number"),
            )
            db.add(existing)
        else:
            existing.value = Decimal(str(found["value"]))
        meta_extracts[metric] = {
            "value": found["value"],
            "fiscal_year": year,
            "method": found["method"],
            "quote": found["quote"],
            "note": note,
            "label": "extraído del informe anual (inferido)",
        }
        written[metric] = found["value"]
    document.metadata_ = {**(document.metadata_ or {}), "sector_extracts": meta_extracts}
    db.flush()
    return {"status": "ok", "fiscal_year": year, "extracted": written}


def extract_provenance(db: Session, fact_id: int | None) -> dict[str, Any] | None:
    """Metodo, cita y cotejo guardados para un hecho extraido (o None)."""
    if fact_id is None:
        return None
    fact = db.get(FinancialFact, fact_id)
    if fact is None or fact.source_type != EXTRACT_SOURCE_TYPE or fact.source_id is None:
        return None
    document = db.get(Document, fact.source_id)
    if document is None:
        return None
    entry = ((document.metadata_ or {}).get("sector_extracts") or {}).get(fact.metric) or {}
    return {
        "method": entry.get("method") or "extraído del texto del informe anual",
        "note": entry.get("note") or SINGLE_SOURCE_NOTE,
        "quote": entry.get("quote"),
        "source_title": document.title,
        "source_url": document.source_url,
        "form": (document.metadata_ or {}).get("form"),
    }
