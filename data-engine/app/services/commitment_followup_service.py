"""Deterministic follow-up over explicit criteria and primary reported evidence.

No network, LLM, writes, fuzzy metric mapping, implicit FX/scaling or invented
partial tolerance. The caller owns source ingestion and tenant-scoped storage.
A literal normalized table row is the deliberately narrow supported evidence
format; a headline, forecast or bare URL cannot establish an outcome.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit


@dataclass(frozen=True)
class FollowupCriterion:
    tenant_id: int
    company_id: int
    promise_id: int
    metric: str | None
    operator: str | None
    target: Decimal | None
    unit: str | None
    period: str | None
    period_end: date | None
    promised_on: date
    due_on: date | None
    basis: str  # declared_structured or verified_structured, never extractor_guess


@dataclass(frozen=True)
class FollowupEvidence:
    tenant_id: int
    company_id: int
    fact_id: int
    document_id: int
    chunk_id: int
    metric: str
    value: Decimal
    unit: str
    period: str
    period_end: date
    published_on: date
    source_url: str
    excerpt: str
    reported: bool
    adjusted: bool
    # This must come from the verified ingestion adapter, NOT source text.
    primary_source_verified: bool
    quote_verified: bool
    checked_at: date
    kind: Literal['financial_fact'] = 'financial_fact'

    @property
    def quote(self) -> str:
        return self.excerpt

    @property
    def document_url(self) -> str:
        return self.source_url

    @property
    def is_reported(self) -> bool:
        return self.reported


@dataclass(frozen=True)
class FollowupResult:
    commitment_id: int
    status: Literal['fulfilled', 'partially_fulfilled', 'missed', 'not_verifiable', 'insufficient_evidence', 'pending']
    basis: Literal['automatic_financial_fact', 'automatic_document_quote', 'none']
    evidence: tuple[FollowupEvidence, ...]
    reason_code: Literal['criterion_matched', 'criterion_not_matched', 'no_comparable_criterion', 'no_reported_fact', 'source_not_official', 'target_not_due', 'ambiguous_metric', 'unit_mismatch', 'period_mismatch', 'future_source', 'conflicting_facts', 'invalid_quote', 'invalid_dates']
    suggestion_only: bool = True
    provenance: Literal['system_checked'] = 'system_checked'


def _https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and bool(parsed.hostname)
                and not parsed.username and not parsed.password)
    except ValueError:
        return False


def _literal_row(evidence: FollowupEvidence) -> bool:
    """A full row, not numeric coincidence elsewhere in a document.

    Only machine-readable normalized metric | decimal | unit | exact period.
    Localized numbers or prose need a separate audited ingestion adapter.
    """
    for line in evidence.excerpt.splitlines():
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) != 4 or cells[0] != evidence.metric or cells[2:] != [evidence.unit, evidence.period]:
            continue
        if not re.fullmatch(r'-?\d+(?:\.\d+)?', cells[1]):
            continue
        if Decimal(cells[1]) == evidence.value:
            return True
    return False


def evaluate_followup(
    criterion: FollowupCriterion, evidence: tuple[FollowupEvidence, ...], *, today: date,
) -> FollowupResult:
    """Read-only suggestion. Time elapsed alone NEVER means missed.

    Different comparable reported values are a conflict, not an invitation to
    pick whichever was ingested last. Restatements need explicit resolution.
    Provenance flags are input attestations from the trusted ingestion adapter,
    not claims read from the external document. This function does not fetch or
    independently authenticate documents. Untrusted payloads need the adapter.
    """
    def result(status, reason, items=()):
        return FollowupResult(criterion.promise_id, status,
                              'automatic_financial_fact' if items else 'none',
                              tuple(items), reason)

    if (type(criterion.tenant_id) is not int or criterion.tenant_id < 1
            or type(criterion.company_id) is not int or criterion.company_id < 1):
        raise ValueError('Se requiere tenant y empresa explícitos')
    if (criterion.basis not in {'declared_structured', 'verified_structured'}
            or not criterion.metric or not criterion.unit or not criterion.period
            or criterion.operator not in {'>', '>=', '<', '<=', '=='}
            or criterion.target is None or not criterion.target.is_finite()
            or criterion.period_end is None or criterion.due_on is None):
        return result('not_verifiable', 'no_comparable_criterion')
    if (criterion.promised_on > today or criterion.period_end < criterion.promised_on
            or criterion.due_on < criterion.promised_on or criterion.period_end > criterion.due_on):
        return result('not_verifiable', 'invalid_dates')
    if today <= criterion.due_on:
        return result('pending', 'target_not_due')
    accepted = []
    rejected = set()
    for item in evidence:
        if item.tenant_id != criterion.tenant_id or item.company_id != criterion.company_id:
            continue
        if item.metric != criterion.metric:
            rejected.add('ambiguous_metric')
        elif item.unit != criterion.unit:
            rejected.add('unit_mismatch')
        elif item.period != criterion.period or item.period_end != criterion.period_end:
            rejected.add('period_mismatch')
        elif not item.value.is_finite() or not item.reported or item.adjusted:
            rejected.add('no_reported_fact')
        elif not item.primary_source_verified or not _https_url(item.source_url):
            rejected.add('source_not_official')
        elif not (criterion.period_end <= item.published_on <= today
                  and criterion.promised_on <= item.published_on
                  and item.published_on <= item.checked_at <= today):
            rejected.add('future_source')
        elif not item.quote_verified or not 1 <= len(item.excerpt) <= 300 or not _literal_row(item):
            rejected.add('invalid_quote')
        else:
            accepted.append(item)
    if not accepted:
        # A stable closed reason, independent of retrieval order.
        reason = next((key for key in ('source_not_official', 'future_source', 'invalid_quote',
                       'unit_mismatch', 'period_mismatch', 'ambiguous_metric', 'no_reported_fact')
                       if key in rejected), 'no_reported_fact')
        return result('insufficient_evidence', reason)
    accepted.sort(key=lambda item: (item.fact_id, item.document_id, item.chunk_id, item.source_url))
    if len({item.value for item in accepted}) != 1:
        return result('insufficient_evidence', 'conflicting_facts', accepted)
    actual, target = accepted[0].value, criterion.target
    met = {'>': actual > target, '>=': actual >= target, '<': actual < target,
           '<=': actual <= target, '==': actual == target}[criterion.operator]
    return result('fulfilled' if met else 'missed',
                  'criterion_matched' if met else 'criterion_not_matched', accepted)


def run_followup_batch(
    criteria: tuple[FollowupCriterion, ...], evidence: tuple[FollowupEvidence, ...],
    *, tenant_id: int, today: date, limit: int = 200,
) -> tuple[FollowupResult, ...]:
    """Bounded pure batch. Reject mixed scopes instead of silently leaking rows.

    Re-running has no effects; persistence/scheduling is a separate adapter.
    """
    if type(tenant_id) is not int or tenant_id < 1 or not 1 <= limit <= 1000:
        raise ValueError('Tenant o límite no válido')
    if len(evidence) > 10000:
        raise ValueError('Demasiadas evidencias: paginar explícitamente')
    if len(criteria) > limit:
        raise ValueError('Lote demasiado grande; paginar explícitamente sin truncar compromisos')
    if any(item.tenant_id != tenant_id for item in (*criteria, *evidence)):
        raise ValueError('Lote con datos de otro tenant')
    if len({item.promise_id for item in criteria}) != len(criteria):
        raise ValueError('Compromiso duplicado en el lote')
    return tuple(evaluate_followup(item, evidence, today=today) for item in criteria)


def load_reported_evidence(
    db, criterion: FollowupCriterion, *, official_urls: frozenset[str], today: date,
    max_facts: int = 200, max_chunks_per_document: int = 1000,
) -> tuple[FollowupEvidence, ...]:
    """Opt-in read adapter. Never commits, flushes, fetches URLs or writes.

    official_urls must be supplied by the verified source registry for THIS
    company, not from arbitrary source text. A public host alone is not proof.
    Trust boundary: a literal normalized table row must exist in DocumentChunk
    and the reported value must be anchored to that same company's Document.
    Current ingesters often lack such rows; that honestly yields no evidence.
    """
    from sqlalchemy import select

    from app.models.entities import Document, DocumentChunk, FinancialFact

    if db.dirty or db.new or db.deleted:
        raise ValueError('La lectura exige una sesión sin cambios pendientes')
    if db.info.get('tenant_id') != criterion.tenant_id or criterion.tenant_id < 1:
        raise ValueError('La sesión no corresponde al tenant del compromiso')
    if not 1 <= max_facts <= 1000 or not 1 <= max_chunks_per_document <= 2000:
        raise ValueError('Límites no válidos')
    with db.no_autoflush:
        pairs = db.execute(select(FinancialFact, Document).join(
            Document, FinancialFact.source_id == Document.id,
        ).where(
            FinancialFact.tenant_id == criterion.tenant_id,
            Document.tenant_id == criterion.tenant_id,
            FinancialFact.company_id == criterion.company_id,
            Document.company_id == criterion.company_id,
            FinancialFact.metric == criterion.metric,
            FinancialFact.is_reported.is_(True),
            FinancialFact.is_adjusted.is_(False),
        ).order_by(FinancialFact.id).limit(max_facts + 1)).all()
        if len(pairs) > max_facts:
            raise ValueError('Demasiados hechos: paginar explícitamente antes de evaluar')
        results = []
        for fact, document in pairs:
            url = document.source_url or ''
            # Do not label a provider snapshot's generic URL as the filing.
            if url not in official_urls or not _https_url(url) or document.published_at is None:
                continue
            if (document.source_type not in {'SEC', 'ESEF', 'primary_official'}
                    or fact.source_type != document.source_type):
                continue
            # Exact dated periods only. No year/quarter guessing, no fiscal
            # year = calendar year assumption, no normalized forecast periods.
            period_match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})(?::(FY|Q[1-4]))?', fact.period)
            if not period_match:
                continue
            try:
                period_end = date.fromisoformat(period_match[1])
            except ValueError:
                continue
            if period_end != criterion.period_end or fact.period != criterion.period:
                continue
            chunks = db.scalars(select(DocumentChunk).where(
                DocumentChunk.tenant_id == criterion.tenant_id,
                DocumentChunk.document_id == document.id,
            ).order_by(DocumentChunk.id).limit(max_chunks_per_document + 1)).all()
            if len(chunks) > max_chunks_per_document:
                raise ValueError('Documento demasiado grande: localizar cita explícitamente antes de evaluar')
            for chunk in chunks:
                for line in chunk.text.splitlines():
                    item = FollowupEvidence(
                        tenant_id=criterion.tenant_id, company_id=criterion.company_id,
                        fact_id=fact.id, document_id=document.id, chunk_id=chunk.id,
                        metric=fact.metric, value=fact.value, unit=fact.unit,
                        period=fact.period, period_end=period_end,
                        published_on=document.published_at.date(), source_url=url,
                        excerpt=line.strip(), reported=True, adjusted=False,
                        primary_source_verified=True, quote_verified=True, checked_at=today,
                    )
                    if _literal_row(item) and 1 <= len(item.excerpt) <= 300:
                        results.append(item)
                        break
                else:
                    continue
                break
        return tuple(results)
