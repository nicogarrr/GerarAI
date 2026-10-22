"""Puente PipelineResult -> FollowupEvidence (puro, sin I/O).

El periodo/fecha de corte NO salen del texto: los aporta quien llama desde el criterio
declarado y se exige que el periodo coincida con el del activo registrado. El motor sigue
siendo suggestion_only; aqui no hay veredictos.
"""

from __future__ import annotations

from datetime import date

from app.services.commitment_followup_service import FollowupEvidence
from app.services.commitment_primary_pipeline import PipelineResult


def evidence_from_pipeline(
    out: PipelineResult, *, document_id: int, chunk_id: int, period_end: date, adjusted: bool = False,
) -> FollowupEvidence | None:
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
