"""Frontera confiable PipelineResult + filas autenticas -> FollowupEvidence.

El motor NO acepta un document_quote construido por un llamador: solo lo decide si lleva el
sello que pone esta funcion tras REVALIDAR contra el texto original:
- el resultado debe estar sellado por la tuberia y su texto debe recalcular a text_sha256;
- el hecho sale de la fila FinancialFact (reportado, no ajustado, mismo valor/unidad) y su
  documento fuente debe tener la URL exacta del activo; el periodo sale de fiscal_year +
  fiscal_quarter explicitos y el corte de la fecha del propio hecho (sin calendario inferido);
- la cita se recalcula con el adaptador estrecho sobre el texto (no basta "el numero aparece"):
  guidance ("We expect growth of 22%") o cifras sueltas ("22 offices") no pasan.
Sin corte de periodo autentico -> None (falla cerrado). El motor sigue siendo suggestion_only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import date

from app.services import commitment_followup_service as engine
from app.services.commitment_followup_service import FollowupEvidence
from app.services.commitment_primary_pipeline import PipelineResult, is_issued_by_pipeline
from app.services.followup_primary_evidence_adapter import (
    ReportedObservation,
    extract_primary_evidence,
)


def period_end_from_fact_period(fact_period: str | None) -> date | None:
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})(?::|$)', fact_period or '')
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def evidence_from_pipeline(
    out: PipelineResult, *, tenant_id: int, company_id: int, fact, source_document,
    chunk_id: int = 0,
) -> FollowupEvidence | None:
    """`fact` = fila FinancialFact y `source_document` = su Document, leidos de BD por el servicio."""
    if not is_issued_by_pipeline(out) or out.result.evidence is None:
        return None
    doc = out.document
    if hashlib.sha256(doc.text.encode()).hexdigest() != doc.text_sha256:
        return None
    quarter = getattr(fact, 'fiscal_quarter', None)
    year = getattr(fact, 'fiscal_year', None)
    if (quarter not in {'Q1', 'Q2', 'Q3', 'Q4'} or type(year) is not int
            or not getattr(fact, 'is_reported', False) or getattr(fact, 'is_adjusted', True)):
        return None
    period = f'{quarter} {year}'
    period_end = period_end_from_fact_period(getattr(fact, 'period', None))
    if period_end is None or period != doc.asset.period:
        return None
    if source_document is None or source_document.source_url != doc.url:
        return None
    observation = ReportedObservation(
        tenant_id, company_id, fact.id, fact.metric, fact.value, fact.unit, doc.url, period,
        True, False,
    )
    check = extract_primary_evidence(
        tenant_id=tenant_id, company_id=company_id, asset=doc.asset, source_url=doc.url,
        original_text=doc.text, fact=observation, today=out.result.evidence.checked_at,
    )
    quote = check.evidence
    if quote is None or quote != out.result.evidence or doc.text[quote.char_start:quote.char_end] != quote.quote:
        return None
    return replace(
        FollowupEvidence(
            tenant_id=tenant_id, company_id=company_id, fact_id=fact.id,
            document_id=source_document.id, chunk_id=chunk_id, metric=quote.metric,
            value=quote.value, unit=quote.unit, period=period, period_end=period_end,
            published_on=quote.published_on, source_url=quote.document_url, excerpt=quote.quote,
            reported=True, adjusted=False, primary_source_verified=True, quote_verified=True,
            checked_at=quote.checked_at, quote_kind='document_quote', page=quote.page,
            char_start=quote.char_start, char_end=quote.char_end, text_sha256=quote.text_sha256,
            bytes_sha256=doc.bytes_sha256, extractor=doc.extractor,
        ),
        _proof=engine._PROOF,
    )
