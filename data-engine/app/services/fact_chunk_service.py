"""Chunks buscables (RAG) generados desde financial_facts reales.

Los Document de fundamentales (SEC/ESEF) se crean sin contenido parseado, asi
que rebuild_tenant no indexaba ningun dato financiero: el RAG solo tenia la
biblioteca de conocimiento. Este servicio genera un chunk por empresa,
ejercicio y fuente con las cifras persistidas en financial_facts (ningun
numero se escribe a mano; el texto declara su fuente), los cuelga del Document
fuente y los regenera en cada refresh de fundamentales. RAGIndex los indexa
despues (ingest_document / rebuild_tenant).
"""
from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Document, DocumentChunk, FinancialFact
from app.models.entities import ClaimEvidence, EvidenceSuggestion, KPIExtractionCandidate

FACT_SOURCES = ("SEC", "ESEF")
_YEAR_RE = re.compile(r"ejercicio fiscal (\d{4})")


def _tombstone_text(company: Company, source: str, year: int | None) -> str:
    label = f"ejercicio fiscal {year}" if year is not None else "ejercicio sin determinar"
    return (
        f"{company.name} ({company.ticker}) - {label} (fuente {source}): "
        "hechos retirados, ya no vigentes. Sin cifras."
    )


def _referenced_chunk_ids(db: Session, chunk_ids: list[int]) -> set[int]:
    """Ids de chunk citados por evidencia o candidatos KPI (FK sin ON DELETE)."""
    if not chunk_ids:
        return set()
    refs: set[int] = set()
    for model in (ClaimEvidence, EvidenceSuggestion, KPIExtractionCandidate):
        rows = db.scalars(
            select(model.document_chunk_id).where(model.document_chunk_id.in_(chunk_ids))
        ).all()
        refs.update(row for row in rows if row is not None)
    return refs

METRIC_LABELS: dict[str, str] = {
    "revenue": "ingresos",
    "revenue_growth": "crecimiento de ingresos",
    "gross_margin": "margen bruto",
    "operating_income": "resultado operativo",
    "operating_margin": "margen operativo",
    "ebitda": "EBITDA",
    "net_income": "beneficio neto",
    "net_margin": "margen neto",
    "eps_diluted": "BPA diluido",
    "income_before_tax": "resultado antes de impuestos",
    "income_tax_expense": "impuesto sobre beneficios",
    "effective_tax_rate": "tipo impositivo efectivo",
    "interest_expense": "gastos financieros",
    "operating_cash_flow": "flujo de caja operativo",
    "capital_expenditure": "capex",
    "free_cash_flow": "flujo de caja libre",
    "depreciation_amortization": "depreciacion y amortizacion",
    "dividends_paid": "dividendos pagados",
    "common_stock_repurchased": "recompra de acciones",
    "cash_and_equivalents": "caja y equivalentes",
    "total_assets": "activos totales",
    "total_liabilities": "pasivos totales",
    "total_equity": "patrimonio neto",
    "debt_to_equity": "deuda sobre patrimonio",
}

_RATIO_UNITS = {"decimal", "ratio", "percent"}


def _es_number(value: float) -> str:
    """1.234,56 en notacion es-ES."""
    return f"{value:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def _format_value(value: Decimal, unit: str) -> str:
    number = float(value)
    unit_clean = unit.replace("iso4217:", "")
    if unit_clean in _RATIO_UNITS:
        return f"{_es_number(number * 100)} %"
    if unit_clean.endswith("/share") or unit_clean.endswith("/xbrli:shares"):
        return f"{_es_number(number)} {unit_clean.split('/')[0]}/acción"
    absolute = abs(number)
    if absolute >= 1e9:
        return f"{_es_number(number / 1e9)} mil M {unit_clean}"
    if absolute >= 1e6:
        return f"{_es_number(number / 1e6)} M {unit_clean}"
    return f"{_es_number(number)} {unit_clean}"


def _render_chunk(
    company: Company,
    source: str,
    fiscal_year: int,
    facts: list[FinancialFact],
) -> str:
    ordered = sorted(
        facts,
        key=lambda f: (list(METRIC_LABELS).index(f.metric) if f.metric in METRIC_LABELS else len(METRIC_LABELS), f.metric),
    )
    parts = [
        f"{METRIC_LABELS.get(fact.metric, fact.metric)} {_format_value(fact.value, fact.unit)}"
        for fact in ordered
        if fact.value is not None
    ]
    return (
        f"{company.name} ({company.ticker}) - ejercicio fiscal {fiscal_year} "
        f"(fuente {source}, hechos reportados): " + "; ".join(parts) + "."
    )


def sync_company_fact_chunks(db: Session, company: Company) -> dict[str, int]:
    """Regenera los chunks RAG del Document SEC/ESEF de la empresa desde sus
    financial_facts actuales. Idempotente: borra y reescribe. Si no quedan
    hechos de una fuente, sus chunks desaparecen (estado honesto)."""
    stats = {"sources": 0, "chunks": 0}
    for source in FACT_SOURCES:
        document = db.scalar(
            select(Document)
            .where(Document.company_id == company.id, Document.source_type == source)
            .order_by(Document.id)
            .limit(1)
        )
        if document is None:
            continue
        facts = list(
            db.scalars(
                select(FinancialFact).where(
                    FinancialFact.company_id == company.id,
                    FinancialFact.source_type == source,
                )
            ).all()
        )
        by_year: dict[int, list[FinancialFact]] = {}
        for fact in facts:
            if fact.fiscal_year is not None and fact.value is not None:
                by_year.setdefault(fact.fiscal_year, []).append(fact)
        texts = {
            year: _render_chunk(company, source, year, year_facts)
            for year, year_facts in by_year.items()
        }
        # Reconcilia POR EJERCICIO y en sitio: un chunk citado por evidencia no
        # se puede borrar sin romper su FK; conserva su id al refrescar sus cifras
        # y, si su ejercicio desaparece, queda como lapida sin cifras.
        existing = list(
            db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
        )
        referenced = _referenced_chunk_ids(db, [chunk.id for chunk in existing])
        matched: set[int] = set()
        kept: list[tuple[int, DocumentChunk]] = []
        for chunk in existing:
            match = _YEAR_RE.search(chunk.text or "")
            year = int(match.group(1)) if match else None
            if year is not None and year in texts and year not in matched:
                matched.add(year)
                chunk.text = texts[year]
                chunk.token_count = len(texts[year].split())
                kept.append((year, chunk))
            elif chunk.id in referenced:
                # Citado pero sin hechos vigentes: lapida SIN cifras. La FK
                # impide borrarlo; el RAG no debe recuperar cifras retiradas.
                chunk.text = _tombstone_text(company, source, year)
                chunk.token_count = len(chunk.text.split())
                chunk.metadata_ = {**(chunk.metadata_ or {}), "obsolete": True}
                kept.append((year if year is not None else -1, chunk))
            else:
                db.delete(chunk)
        db.flush()
        for year, text in texts.items():
            if year not in matched:
                new_chunk = DocumentChunk(
                    document_id=document.id, chunk_index=0, text=text, token_count=len(text.split())
                )
                db.add(new_chunk)
                kept.append((year, new_chunk))
        for index, (_year, chunk) in enumerate(sorted(kept, key=lambda item: item[0], reverse=True)):
            chunk.chunk_index = index
        stats["chunks"] += len(texts)
        stats["sources"] += 1
    db.flush()
    return stats
