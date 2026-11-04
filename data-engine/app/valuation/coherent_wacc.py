"""Pure sourced annual/TTM borrowing-cost diagnostics and explicit-policy WACC.

Cash interest / mean carrying debt is a historical financing-cost proxy, not a
current marginal borrowing yield. Net interest is a separate, named proxy, never
silently gross interest. Accounting ETR is not the realized cash interest shield.
No defaults, clipping to g, capitalization bands, network or persistence.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class DatedAssumption:
    value: Decimal
    observed: date
    published: date
    source_url: str
    reference: str
    unit: str


CASH_INTEREST = 'InterestPaidNet'
NET_INTEREST = 'InterestIncomeExpenseNonoperatingNet'
DEBT = 'LongTermDebt'
TAX = 'IncomeTaxExpenseBenefit'
PRETAX = 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'


def sourced_financing_cost(payload: dict, *, source_url: str, end: date,
                           as_of: date, currency: str, interest_basis: str,
                           debt_concept: str, debt_scope: str) -> dict:
    """Annual end or FY+current YTD-prior YTD, exact economic boundaries.

    Caller must name debt scope. No current maturity double count or guessing
    debt completeness. Each duration's interest/tax/pretax comes from one filing;
    opening/closing balances retain their own explicit document references.
    A partial year is not divided by debt as though it were annual interest.
    """
    out = {'status': 'not_available', 'cost_of_debt_proxy': None,
           'annual_interest': None, 'mean_debt': None, 'closing_debt': None,
           'accounting_etr_proxy': None, 'interest_basis': interest_basis,
           'debt_scope': debt_scope, 'currency': currency, 'end': end,
           'sources': [], 'missing': [], 'warnings': [
               'historical_cost_not_current_marginal_yield',
               'accounting_etr_not_cash_interest_tax_shield']}
    if interest_basis not in {'cash_paid', 'net_interest_expense'} or not debt_scope or not debt_concept:
        return {**out, 'missing': ['explicit_interest_basis_and_debt_scope']}
    if not source_url.startswith('https://data.sec.gov/') or end > as_of:
        return {**out, 'missing': ['source_or_cutoff']}
    concept = CASH_INTEREST if interest_basis == 'cash_paid' else NET_INTEREST
    concepts = payload.get('facts', {}).get('us-gaap', {})

    def rows(name, start, finish):
        matches = []
        for row in concepts.get(name, {}).get('units', {}).get(currency, []):
            try:
                filed = date.fromisoformat(row['filed'])
                value = Decimal(str(row['val']))
                if (row.get('start') == (start.isoformat() if start else None)
                        and row.get('end') == finish.isoformat() and finish <= filed <= as_of
                        and row.get('form') in {'10-K', '10-Q', '10-K/A', '10-Q/A'}
                        and row.get('accn') and value.is_finite()):
                    matches.append((filed, row['accn'], value))
            except (KeyError, ValueError, InvalidOperation, TypeError):
                continue
        return matches

    def group(names, start, finish):
        sets = {name: rows(name, start, finish) for name in names}
        docs = None
        for candidates in sets.values():
            identifiers = {(filed, accn) for filed, accn, _ in candidates}
            docs = identifiers if docs is None else docs & identifiers
        if not docs:
            raise ValueError(f'missing_coherent_statement:{start}:{finish}')
        filed, doc = max(docs)
        values = {}
        for name, candidates in sets.items():
            amounts = {val for f, d, val in candidates if (f, d) == (filed, doc)}
            if len(amounts) != 1:
                raise ValueError(f'conflicting_values:{name}')
            values[name] = next(iter(amounts))
            out['sources'].append({'concept': name, 'value': str(values[name]),
                                   'start': start, 'end': finish, 'filed': filed,
                                   'accession': doc, 'source_url': source_url})
        return values

    try:
        if end.month == 12 and end.day == 31:
            start = date(end.year, 1, 1)
            totals = group((concept, TAX, PRETAX), start, end)
            prior_end = date(end.year-1, 12, 31)
            method = 'reported_annual'
        elif end.month in {3, 6, 9} and end.day == (date(end.year, end.month+1, 1)-timedelta(days=1)).day:
            prior_end = date(end.year-1, end.month, end.day)
            annual = group((concept, TAX, PRETAX), date(end.year-1, 1, 1), date(end.year-1, 12, 31))
            current = group((concept, TAX, PRETAX), date(end.year, 1, 1), end)
            previous = group((concept, TAX, PRETAX), date(end.year-1, 1, 1), prior_end)
            totals = {key: annual[key]+current[key]-previous[key] for key in (concept, TAX, PRETAX)}
            method = 'annual_plus_current_ytd_minus_prior_ytd'
            start = prior_end+timedelta(days=1)
        else:
            raise ValueError('unsupported_calendar_period')
        opening = group((debt_concept,), None, prior_end)[debt_concept]
        closing = group((debt_concept,), None, end)[debt_concept]
        if opening <= 0 or closing <= 0:
            raise ValueError('positive_complete_debt_balances_required')
        annual_interest = totals[concept] if interest_basis == 'cash_paid' else -totals[concept]
        if annual_interest < 0:
            raise ValueError('net_interest_income_not_borrowing_cost')
        mean = (opening+closing)/Decimal(2)
        kd = annual_interest/mean
        if kd > Decimal('.50'):
            raise ValueError('cost_of_debt_out_of_bounds')
        etr = totals[TAX]/totals[PRETAX] if totals[PRETAX] > 0 else None
        if etr is not None and not Decimal(0) <= etr <= Decimal(1):
            etr = None
        return {**out, 'status': 'ok', 'cost_of_debt_proxy': kd,
                'annual_interest': annual_interest, 'mean_debt': mean, 'closing_debt': closing,
                'opening_debt': opening, 'accounting_etr_proxy': etr,
                'start': start, 'method': method, 'annual_tax_expense': totals[TAX],
                'annual_pretax_income': totals[PRETAX]}
    except ValueError as exc:
        return {**out, 'missing': [str(exc)]}


def explicit_policy_wacc(financing: dict, inputs: dict[str, DatedAssumption], *,
                         as_of: date, tax_policy: str) -> dict:
    """WACC diagnostic, never unlabelled authority to write valuation inputs.

    CAPM market assumptions (Rf/beta/ERP/CRP/E) must have dates and provenance;
    nominal rates and currency must match. Explicit tax choice: supplied marginal
    assumption or accounting ETR proxy. No implied full shield or implicit zero.
    """
    result = {'status': 'not_available', 'wacc': None, 'missing': [],
              'tax_policy': tax_policy, 'financing': financing,
              'inputs': inputs, 'method': 'CAPM_market_equity_carrying_debt_historical_cost_proxy'}
    if financing.get('status') != 'ok':
        return {**result, 'missing': ['coherent_financing_cost']}
    needed = {'risk_free_rate', 'beta', 'equity_risk_premium', 'country_risk_premium', 'market_equity'}
    if tax_policy == 'supplied_marginal_assumption':
        needed.add('tax_rate')
    elif tax_policy != 'accounting_etr_proxy':
        return {**result, 'missing': ['explicit_tax_policy']}
    missing = sorted(needed-inputs.keys())
    if missing:
        return {**result, 'missing': missing}
    for key in needed:
        item = inputs[key]
        expected = financing['currency'] if key == 'market_equity' else 'ratio' if key == 'beta' else 'decimal'
        if (not item.value.is_finite() or item.value < 0 or item.unit != expected
                or not item.reference or not item.source_url.startswith('https://')
                or item.observed > as_of or item.published > as_of
                or (as_of-item.observed).days > 45):
            return {**result, 'missing': [f'invalid_or_stale:{key}']}
    observed = [inputs[k].observed for k in needed if k != 'tax_rate']
    if (max(observed)-min(observed)).days > 31:
        return {**result, 'missing': ['incoherent_market_dates']}
    v = {k: inputs[k].value for k in needed}
    if not (v['market_equity'] > 0 and 0 < v['beta'] <= 5 and
            0 < v['equity_risk_premium'] <= Decimal('.20') and v['risk_free_rate'] <= Decimal('.20')
            and v['country_risk_premium'] <= Decimal('.20')):
        return {**result, 'missing': ['economic_bounds']}
    tax = v['tax_rate'] if tax_policy == 'supplied_marginal_assumption' else financing['accounting_etr_proxy']
    if tax is None or not 0 <= tax <= 1:
        return {**result, 'missing': ['tax_rate']}
    ke = v['risk_free_rate']+v['beta']*v['equity_risk_premium']+v['country_risk_premium']
    debt, equity = financing['closing_debt'], v['market_equity']
    wd = debt/(debt+equity)
    we = equity/(debt+equity)
    kd = financing['cost_of_debt_proxy']
    return {**result, 'status': 'indicative_proxy', 'wacc': we*ke+wd*kd*(1-tax),
            'cost_of_equity': ke, 'equity_weight': we, 'debt_weight': wd,
            'cost_of_debt_proxy': kd, 'tax_rate': tax,
            'tax_is_observed_cash_interest_shield': False}
