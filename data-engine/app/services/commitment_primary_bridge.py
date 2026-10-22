"""Puente PipelineResult -> FollowupEvidence (puro, sin I/O).

El corte del periodo NO sale del texto ni del criterio: se toma del `period` del
FinancialFact reportado ('YYYY-MM-DD[:Qn|:FY]'); sin fecha de corte autentica -> None
(se rechaza antes de canonizar estado). Solo acepta PipelineResult emitido por la tuberia. El motor sigue
siendo suggestion_only; aqui no hay veredictos.
"""

from __future__ import annotations

import re
from datetime import date

from app.services.commitment_followup_service import FollowupEvidence
from app.services.commitment_primary_pipeline import PipelineResult, is_issued_by_pipeline


def period_end_from_fact_period(fact_period: str | None) -> date | None:
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})(?::|$)', fact_period or '')
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def evidence_from_pipeline(
    out: PipelineResult, *, document_id: int, chunk_id: int, fact_period: str | None,
    adjusted: bool = False,
) -> FollowupEvidence | None:
    if not is_issued_by_pipeline(out):
        return None
    period_end = period_end_from_fact_period(fact_period)
    if period_end is None:
        return None
    quote = out.result.evidence
    if quote is None or quote.kind != 'document_quote' or quote.period != out.document.asset.period:
        return None
    return FollowupEvidence(
        tenant_id=quote.tenant_id, company_id=quote.company_id, fact_id=quote.fact_id,
        document_id=document_id, chunk_id=chunk_id, metric=quote.metric, value=quote.value,
        unit=quote.unit, period=quote.period, period_end=period_end,
        published_on=quote.published_on, source_url=quote.document_url, excerpt=quote.quote,
        reported=True, adjusted=adjusted, primary_source_verified=True, quote_verified=True,
        checked_at=quote.checked_at, quote_kind='document_quote', page=quote.page,
        char_start=quote.char_start, char_end=quote.char_end, text_sha256=quote.text_sha256,
        bytes_sha256=out.document.bytes_sha256, extractor=out.document.extractor,
    )
