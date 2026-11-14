"""Informe frente al mismo periodo del ano anterior: cifras clave + cambios de texto.

Solo lee lo ya guardado (hechos financieros y el analisis persistido por
``filing_intelligence``); no descarga, no analiza y no llama a ningun LLM.
Cada cifra lleva su periodo y la fuente del hecho. Las variaciones son
aritmetica sobre dos cifras oficiales (DERIVADO), nunca un juicio.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from heapq import nlargest
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, FinancialFact
from app.services.filing_changes import comparable, reported_period
from app.services.filing_intelligence import KEY, official_document

FORMS = ("10-K", "10-Q")
MAX_DOCUMENTS = 200
# Variacion a partir de la cual la fila se marca; umbral de presentacion, no de materialidad.
HIGHLIGHT_PCT = Decimal("10")
FIGURE_METRICS = (
    "revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
    "operating_cash_flow", "capital_expenditure", "free_cash_flow", "total_assets",
    "total_liabilities", "total_equity", "cash_and_equivalents", "total_debt",
    "shares_diluted",
)
# Metricas que se guardan en NEGATIVO por ser salida de caja (capex). Variacion y
# presentacion sobre el importe absoluto: un capex que sube no es un "recorte".
OUTFLOW_METRICS = frozenset({"capital_expenditure"})
LABEL_OFFICIAL = "OFICIAL"
LABEL_DERIVED = "DERIVADO"
LABEL_INFERRED = "INFERIDO"
LABEL_NO_DATA = "SIN_DATOS"


def _end_and_suffix(period: str) -> tuple[date, str] | None:
    head, _, suffix = period.partition(":")
    try:
        return date.fromisoformat(head), suffix
    except ValueError:
        return None


def _anniversary(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def _best(rows: list[FinancialFact]) -> FinancialFact | None:
    """Un hecho por clave: mas confianza, luego el ultimo guardado."""
    if not rows:
        return None
    return max(rows, key=lambda row: (row.confidence, row.created_at.timestamp() if row.created_at else 0.0, row.id))


def _source(db: Session, fact: FinancialFact) -> dict[str, Any]:
    document = db.get(Document, fact.source_id) if fact.source_id else None
    return {
        "url": document.source_url if document is not None and official_document(document) else None,
        "published_at": document.published_at.isoformat() if document is not None and document.published_at else None,
        "source_type": fact.source_type,
    }


def _side(db: Session, fact: FinancialFact) -> dict[str, Any]:
    return {"value": str(fact.value), "period": fact.period, "unit": fact.unit,
            "source": _source(db, fact)}


def figures(db: Session, company_id: int, current_end: date, suffix: str | None) -> list[dict]:
    """Cifras clave de ambos periodos. Sin dato en un lado = SIN_DATOS, no cero."""
    rows = db.scalars(select(FinancialFact).where(
        FinancialFact.tenant_id == db.info["tenant_id"], FinancialFact.company_id == company_id,
        FinancialFact.metric.in_(FIGURE_METRICS), FinancialFact.is_reported.is_(True),
        FinancialFact.is_adjusted.is_(False),
    )).all()
    cur: dict[tuple[str, str], list[FinancialFact]] = {}
    prev: dict[tuple[str, str], list[FinancialFact]] = {}
    for row in rows:
        parsed = _end_and_suffix(row.period)
        if parsed is None:
            continue
        end, fact_suffix = parsed
        if suffix is not None and fact_suffix != suffix:
            continue
        if suffix is None and fact_suffix == "FY":
            continue  # 10-Q sin trimestre explicito: nunca mezclar con cifras anuales.
        key = (row.metric, row.unit)
        if abs((end - current_end).days) <= 3:
            cur.setdefault(key, []).append(row)
        elif abs((end - _anniversary(current_end, -1)).days) <= 15:
            prev.setdefault(key, []).append(row)
    out = []
    for metric in FIGURE_METRICS:
        for key in sorted(k for k in set(cur) | set(prev) if k[0] == metric):
            now, before = _best(cur.get(key, [])), _best(prev.get(key, []))
            outflow = metric in OUTFLOW_METRICS
            item: dict[str, Any] = {"metric": metric, "unit": key[1], "outflow": outflow,
                                    "current": _side(db, now) if now else None,
                                    "previous": _side(db, before) if before else None}
            if now is None or before is None:
                item.update(label=LABEL_NO_DATA, change_pct=None, highlight=False)
            else:
                item["label"] = LABEL_OFFICIAL
                now_value, before_value = ((abs(now.value), abs(before.value)) if outflow
                                           else (now.value, before.value))
                if before_value != 0 and (before_value > 0) == (now_value > 0):
                    pct = (now_value - before_value) / abs(before_value) * 100
                    item.update(change_pct=str(pct.quantize(Decimal("0.1"))),
                                change_label=LABEL_DERIVED, highlight=abs(pct) >= HIGHLIGHT_PCT)
                else:
                    # Base cero o cambio de signo: un % no significa nada.
                    item.update(change_pct=None, change_label=LABEL_NO_DATA, highlight=False)
            out.append(item)
    return out


def _citation(document: Document) -> dict[str, Any]:
    period = reported_period(document.metadata_ or {})
    return {"document_id": document.id, "url": document.source_url,
            "published_at": document.published_at.isoformat() if document.published_at else None,
            "reported_period": period.isoformat() if period else None,
            "label": LABEL_OFFICIAL}


def comparison(db: Session, company_id: int, form: str, page: int) -> dict[str, Any]:
    """Comparacion de la pagina ``page`` (1 = informe mas reciente) para ``form``."""
    if form not in FORMS:
        raise ValueError("form debe ser 10-K o 10-Q")
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise ValueError("Tenant context required")
    # Stream only provenance and period fields, not full metadata/analysis. Validate
    # before the bounded newest-N selection so bad rows cannot displace reports.
    candidates = db.execute(select(
        Document.id, Document.source_url, Document.source_type,
        Document.metadata_["period_of_report"].as_string().label("period_of_report"),
        Document.metadata_["report_date"].as_string().label("report_date"),
    ).where(
        Document.tenant_id == tenant, Document.company_id == company_id,
        Document.metadata_["form"].as_string() == form,
    ).execution_options(yield_per=MAX_DOCUMENTS))
    today = date.today()
    newest = nlargest(MAX_DOCUMENTS, (
        (period, row.id) for row in candidates
        if official_document(row)
        and (period := reported_period({"period_of_report": row.period_of_report,
                                       "report_date": row.report_date})) is not None
        and period <= today
    ))
    # Full documents stay capped; use explicit tenant/company checks on both reads.
    ids = [document_id for _, document_id in newest]
    documents = list(db.scalars(select(Document).where(
        Document.tenant_id == tenant, Document.company_id == company_id,
        Document.id.in_(ids),
    ).limit(MAX_DOCUMENTS)).all()) if ids else []
    documents.sort(key=lambda d: (reported_period(d.metadata_ or {}), d.id), reverse=True)
    base: dict[str, Any] = {"form": form, "page": page, "total": len(documents)}
    if not documents or page > len(documents):
        return {**base, "status": "insufficient_data", "items": [],
                "reason": f"Sin {form} oficial de la SEC guardado para esta empresa."}
    document = documents[page - 1]
    meta = document.metadata_ or {}
    current_end = reported_period(meta)
    assert current_end is not None
    prior = next((d for d in documents if d.id != document.id and comparable(meta, d.metadata_ or {})), None)
    result: dict[str, Any] = {**base, "status": "ready", "current": _citation(document), "previous": None,
                              "figures": [], "text": None}
    if prior is None:
        result.update(status="insufficient_data",
                      reason="Sin informe comparable del mismo periodo del año anterior.")
        return result
    result["previous"] = _citation(prior)
    suffix = "FY" if form == "10-K" else meta.get("fiscal_quarter")
    result["figures"] = figures(db, company_id, current_end, suffix)
    stored = meta.get(KEY) or {}
    diff = stored.get("diff")
    if diff and (stored.get("previous_source") or {}).get("document_id") == prior.id:
        result["text"] = diff
    else:
        result["text_reason"] = "Análisis de texto aún no generado para este informe."
    return result
