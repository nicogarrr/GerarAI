"""Pure, exact-period debt bridge. No retrieval, persistence or missing->zero.

DebtCurrent includes current maturities and short-term debt. Never add another
current concept to it. LongTermDebt includes current maturities: never add those
twice. Noncurrent debt alone cannot establish total debt. Lease-scope additions
are deliberately left to callers as an explicit reported aggregate, not guessed.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class BalanceOperand:
    concept: str
    value: Decimal
    currency: str
    end: date
    filed: date
    document: str
    source_url: str
    reference: str
    official: bool = True


CONCEPTS = frozenset({
    'DebtLongtermAndShorttermCombinedAmount', 'DebtCurrent',
    'LongTermDebtNoncurrent', 'LongTermDebt', 'LongTermDebtCurrent',
    'ShortTermBorrowings', 'CashAndCashEquivalentsAtCarryingValue',
    'ShortTermInvestments', 'MarketableSecuritiesCurrent',
    'RestrictedCashAndCashEquivalentsAtCarryingValue',
})


def sec_balance_operands(payload: dict, *, source_url: str, as_of: date) -> list[BalanceOperand]:
    """Consolidated instant companyfacts, retaining accession and concept.

    No custom-concept guessing. Zero must exist as an explicit numeric SEC fact.
    Absence of borrowing facts, narrative materiality and lease assets prove none.
    """
    result = []
    if not source_url.startswith('https://data.sec.gov/'):
        return result
    for concept, detail in payload.get('facts', {}).get('us-gaap', {}).items():
        if concept not in CONCEPTS:
            continue
        for currency, rows in detail.get('units', {}).items():
            if currency not in {'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY', 'CHF'}:
                continue
            for row in rows:
                if row.get('start') or row.get('form') not in {'10-K', '10-Q', '10-K/A', '10-Q/A'}:
                    continue
                try:
                    end, filed = date.fromisoformat(row['end']), date.fromisoformat(row['filed'])
                    value = Decimal(str(row['val']))
                    document = row['accn']
                    if not document or not value.is_finite() or value < 0 or end > filed or filed > as_of:
                        continue
                except (KeyError, ValueError, InvalidOperation, TypeError):
                    continue
                result.append(BalanceOperand(concept, value, currency, end, filed, document,
                                             source_url, f'{document}:{concept}:{end.isoformat()}'))
    return result


def coherent_debt_bridge(operands: list[BalanceOperand], *, end: date, as_of: date,
                         currency: str, cash_policy: str) -> dict:
    """Same closing date/currency/accession only, latest eligible document.

    cash_only subtracts unrestricted cash equivalents. cash_plus_current_securities
    additionally requires an explicit current-investment fact. Restricted cash is
    never subtracted. These policies must be chosen, not silently switched. No
    stale direct net-debt operand can override the requested closing date.
    """
    if cash_policy not in {'cash_only', 'cash_plus_current_securities'}:
        raise ValueError('explicit_cash_policy_required')
    eligible = [f for f in operands if f.concept in CONCEPTS and f.end == end and f.filed <= as_of and
                f.end <= f.filed and f.currency == currency and f.document and
                f.source_url and f.reference and f.official]
    base = {'status': 'not_available', 'total_debt': None, 'current_debt': None,
            'net_debt': None, 'end': end, 'currency': currency, 'cash_policy': cash_policy,
            'restricted_cash_policy': 'excluded', 'components': [], 'missing': [],
            'latest_available_end': max((f.end for f in operands if f.filed <= as_of
                                         and f.end <= as_of and f.currency == currency), default=None)}
    if not eligible:
        return {**base, 'missing': ['exact_period']}
    newest = max(f.filed for f in eligible)
    documents = {f.document for f in eligible if f.filed == newest}
    if len(documents) != 1:
        return {**base, 'status': 'conflict', 'missing': ['ambiguous_document']}
    doc = next(iter(documents))
    facts = [f for f in eligible if f.document == doc]
    selected = {}
    for concept in CONCEPTS:
        candidates = [f for f in facts if f.concept == concept]
        if not candidates:
            continue
        values = {f.value for f in candidates}
        if len(values) != 1 or any(not v.is_finite() or v < 0 for v in values):
            return {**base, 'status': 'conflict', 'missing': [concept]}
        selected[concept] = candidates[0]

    def pick(*concepts):
        found = [selected[c] for c in concepts if c in selected]
        if len({f.value for f in found}) > 1:
            raise ValueError('conflicting_aliases')
        return found[0] if found else None

    used = []
    try:
        current = pick('DebtCurrent')
        noncurrent = pick('LongTermDebtNoncurrent')
        aggregate = pick('DebtLongtermAndShorttermCombinedAmount')
        total = None
        if aggregate is not None:
            total = aggregate.value
            used.append(aggregate)
            if current is not None and noncurrent is not None and total != current.value + noncurrent.value:
                return {**base, 'status': 'conflict', 'missing': ['aggregate_components_disagree']}
        elif current is not None and noncurrent is not None:
            total = current.value + noncurrent.value
            used.extend([current, noncurrent])
        else:
            # LongTermDebt alone is not all financial debt: short borrowing
            # completeness must be explicit, even when it is reported zero.
            term = pick('LongTermDebt')
            short = pick('ShortTermBorrowings')
            if term is not None and short is not None:
                total = term.value + short.value
                used.extend([term, short])
        if total is None:
            base['missing'].append('complete_debt_aggregate_or_disjoint_components')
        cash = pick('CashAndCashEquivalentsAtCarryingValue')
        if cash is None:
            base['missing'].append('cash_and_equivalents')
        else:
            used.append(cash)
        investments = None
        if cash_policy == 'cash_plus_current_securities':
            investments = pick('ShortTermInvestments', 'MarketableSecuritiesCurrent')
            if investments is None:
                base['missing'].append('current_securities')
            else:
                used.append(investments)
        net = None
        if total is not None and cash is not None and not base['missing']:
            net = total - cash.value
            if investments is not None:
                net -= investments.value
        return {**base, 'status': 'ok' if net is not None else 'not_available',
                'total_debt': total, 'current_debt': current.value if current is not None else None,
                'net_debt': net, 'document': doc, 'filed': newest, 'components': used}
    except ValueError as exc:
        return {**base, 'status': 'conflict', 'missing': [str(exc)]}


def exact_sec_cashflow(payload: dict, *, start: date, end: date, as_of: date,
                       currency: str, source_url: str) -> dict:
    """CFO and capex must be the requested duration in one SEC document.

    SEC companyfacts often contains only YTD. No quarter from older quarter,
    no YTD subtraction and no annualization is performed here.
    """
    concepts = {'operating_cash_flow': 'NetCashProvidedByUsedInOperatingActivities',
                'capital_expenditure': 'PaymentsToAcquirePropertyPlantAndEquipment'}
    available, selected = [], {}
    if not source_url.startswith('https://data.sec.gov/'):
        return {'status': 'not_available', 'facts': {}, 'latest_available_end': None}
    for metric, concept in concepts.items():
        entries = payload.get('facts', {}).get('us-gaap', {}).get(concept, {}).get('units', {}).get(currency, [])
        rows = []
        for row in entries:
            try:
                row_start = date.fromisoformat(row['start'])
                row_end, filed = date.fromisoformat(row['end']), date.fromisoformat(row['filed'])
                value = Decimal(str(row['val']))
                if filed > as_of or row_end > filed or row_start > row_end or not value.is_finite() or not row.get('accn'):
                    continue
                if row.get('form') not in {'10-K', '10-Q', '10-K/A', '10-Q/A'}:
                    continue
                available.append(row_end)
                if row_start == start and row_end == end:
                    rows.append((filed, row['accn'], value))
            except (KeyError, ValueError, InvalidOperation, TypeError):
                continue
        if rows:
            latest = max(r[0] for r in rows)
            candidates = {(doc, value) for filed, doc, value in rows if filed == latest}
            if len(candidates) != 1:
                return {'status': 'conflict', 'facts': {}, 'latest_available_end': max(available)}
            doc, value = next(iter(candidates))
            selected[metric] = {'value': value, 'document': doc, 'filed': latest,
                                'start': start, 'end': end, 'currency': currency,
                                'source_url': source_url, 'concept': concept}
    complete = len(selected) == len(concepts) and len({f['document'] for f in selected.values()}) == 1
    return {'status': 'ok' if complete else 'not_available', 'facts': selected if complete else {},
            'latest_available_end': max(available) if available else None}
