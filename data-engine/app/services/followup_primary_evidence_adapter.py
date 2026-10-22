"""Original-source quote adapter. No I/O, storage, invented rows or verdicts.

Only a narrow, audited past-result grammar is supported. More than/around,
forecasts, adjusted metrics and TTM versus quarter mismatches cannot be turned
into an exact reported observation. Registry authenticity belongs to the caller.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PrimaryAsset:
    """Snapshot supplied from the verified per-ticker EXACT-asset registry.

    Never construct this from fields supplied in external source text.
    """
    ticker: str
    url: str
    period: str  # Q2 2026, exactly as printed in the original header
    published_on: date
    kind: Literal['transcript']


@dataclass(frozen=True)
class ReportedObservation:
    tenant_id: int
    company_id: int
    fact_id: int
    metric: str
    value: Decimal
    unit: str
    source_url: str
    period: str
    reported: bool
    adjusted: bool


@dataclass(frozen=True)
class PrimaryQuote:
    kind: Literal['document_quote']
    tenant_id: int
    company_id: int
    fact_id: int
    metric: str
    value: Decimal
    unit: str
    period: str
    document_url: str
    quote: str
    char_start: int
    char_end: int
    page: int
    text_sha256: str
    published_on: date
    checked_at: date
    provenance: Literal['system_checked'] = 'system_checked'


@dataclass(frozen=True)
class PrimaryEvidenceResult:
    evidence: PrimaryQuote | None
    reason_code: str


# Explicit canonical metric contracts, not a fuzzy mapping/extractor guess.
# Percent means growth, NOT gross bookings amount or percent-point change.
_RULES = {
    # Base EXPLICITA en la frase: moneda constante es una medida ajustada, NO crecimiento
    # reportado en USD (el comunicado de UBER Q2-26 da 24% reportado y 22% moneda constante).
    'gross_bookings_growth_yoy_constant_currency': re.compile(
        r'\bGross bookings grew (?P<value>\d+(?:\.\d+)?)% year-on-year on a constant currency basis\b'),
}
# Metrica -> el hecho debe declararse ajustado (basis explicita en la regla).
_ADJUSTED_METRICS = frozenset({'gross_bookings_growth_yoy_constant_currency'})
# Sin base declarada: NUNCA se deduce "reportado" por ausencia de "constant currency".
_BASIS_UNSTATED = frozenset({'gross_bookings_growth_yoy'})
_FUTURE = re.compile(r'\b(expect\w*|anticipat\w*|guidance|forecast\w*|will|would|aim\w*|target\w*|could|should|project\w*)\b', re.I)


def extract_primary_evidence(
    *, tenant_id: int, company_id: int, asset: PrimaryAsset,
    source_url: str, original_text: str, fact: ReportedObservation, today: date,
) -> PrimaryEvidenceResult:
    """Match an exact reported observation to literal original text.

    Asset must have been authenticated via an IR href by the source registry.
    No authority is taken from the PDF's instructions or its self-description.
    Source text stays in memory; return only a quote <=300 and recoverable span.
    """
    def rejected(reason):
        return PrimaryEvidenceResult(None, reason)

    if type(tenant_id) is not int or tenant_id < 1 or type(company_id) is not int or company_id < 1:
        raise ValueError('Tenant y empresa explícitos obligatorios')
    if fact.tenant_id != tenant_id or fact.company_id != company_id:
        raise ValueError('Observación fuera del tenant o empresa')
    if source_url != asset.url or source_url != fact.source_url or asset.kind != 'transcript':
        return rejected('source_not_official')
    try:
        url = urlsplit(asset.url)
        valid_url = url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        valid_url = False
    if not valid_url or not (asset.published_on <= today):
        return rejected('future_or_invalid_source')
    if fact.metric in _BASIS_UNSTATED:
        return rejected('metric_basis_unstated')
    if not fact.reported or fact.adjusted != (fact.metric in _ADJUSTED_METRICS) or not fact.value.is_finite():
        return rejected('no_reported_fact')
    if not original_text or len(original_text) > 1_500_000:
        return rejected('invalid_text_size')
    # Header period is required, not just the presence of a year in a paragraph.
    header = original_text[:3000]
    if not re.search(rf'\b{re.escape(asset.period)} Earnings Call\b', header, re.I):
        return rejected('period_header_mismatch')
    if not re.search(rf'\({re.escape(asset.ticker)}\)', header):
        return rejected('ticker_header_mismatch')
    # Explicit English month map avoids environment-dependent locale parsing.
    months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
    printed_date = f'{asset.published_on.day:02d}-{months[asset.published_on.month - 1]}-{asset.published_on.year}'
    if printed_date not in header:
        return rejected('date_header_mismatch')
    if fact.period != asset.period:
        return rejected('period_mismatch')
    rule = _RULES.get(fact.metric)
    if rule is None:
        return rejected('unsupported_metric_rule')
    if fact.unit != '%':
        return rejected('unit_mismatch')
    # Sentence boundary anchored to original character offsets. Preserve all
    # original whitespace; never generate a normalized sentence or table row.
    candidates = []
    for match in rule.finditer(original_text):
        start = max(original_text.rfind('.', 0, match.start()), original_text.rfind('\n\n', 0, match.start())) + 1
        boundary = re.search(r'[.!?](?=\s|$)', original_text[match.end():])
        end = match.end() + boundary.end() if boundary else len(original_text)
        while start < end and original_text[start].isspace():
            start += 1
        quote = original_text[start:end]
        # This rule supports the current-quarter results paragraph only, not
        # an arbitrary mention of past growth in Q&A or a comparison year.
        paragraph_start = original_text.rfind('\n\n', 0, match.start())
        context = original_text[max(paragraph_start, match.start() - 500, 0):match.start()]
        quarter = re.fullmatch(r'(Q[1-4]) (\d{4})', asset.period)
        if not quarter or not re.search(rf'\b{quarter[1]} was another outstanding quarter\b', context):
            continue
        if original_text[start:match.start()].strip():
            continue
        # A backward reference to previous guidance AFTER an actual result is
        # fine, but a future/forecast lead-in is not. Reject ambiguous clauses.
        if _FUTURE.search(original_text[start:match.start()]):
            continue
        if not 1 <= len(quote) <= 300 or Decimal(match['value']) != fact.value:
            continue
        candidates.append((start, end, quote))
    if not candidates:
        return rejected('no_literal_comparable_result')
    # Conflicting explicitly reported values in the same source need review.
    values = {Decimal(match['value']) for match in rule.finditer(original_text)
              if not _FUTURE.search(original_text[max(0, original_text.rfind('.', 0, match.start()) + 1):match.start()])}
    if len(values) != 1:
        return rejected('conflicting_source_values')
    start, end, quote = candidates[0]
    return PrimaryEvidenceResult(PrimaryQuote(
        'document_quote', tenant_id, company_id, fact.fact_id, fact.metric,
        fact.value, fact.unit, fact.period, source_url, quote, start, end,
        original_text.count('\f', 0, start) + 1,
        hashlib.sha256(original_text.encode()).hexdigest(), asset.published_on, today,
    ), 'literal_reported_result')


def asset_from_registry(entry, *, source_url: str) -> PrimaryAsset | None:
    """Bridge to SourceEntry/VerifiedAsset without inventing unknown dates.

    Accept only an exact registered transcript and an explicit call_date; an IR
    page checked_on date is NOT the transcript publication/call date. No network.
    The entry must come from the trusted registry module, not request JSON.
    """
    if entry is None or entry.status != 'transcripcion_oficial_pdf':
        return None
    for asset in entry.assets:
        if asset.url != source_url or asset.kind != 'transcript' or not asset.call_date:
            continue
        try:
            source_date = date.fromisoformat(asset.call_date)
        except ValueError:
            return None
        return PrimaryAsset(entry.ticker, asset.url, asset.period, source_date, 'transcript')
    return None
