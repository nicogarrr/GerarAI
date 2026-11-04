import gzip
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.valuation.coherent_wacc import (
    DatedAssumption,
    explicit_policy_wacc,
    sourced_financing_cost,
)

ROOT = Path(__file__).parent / 'fixtures/chtr_wacc'
ASOF = date(2026, 11, 4)


def payload():
    b = gzip.decompress((ROOT/'companyfacts.json.gz').read_bytes())
    assert hashlib.sha256(b).hexdigest() == json.loads((ROOT/'source.json').read_text())['sha256']
    return json.loads(b)


def financing(end=date(2026, 6, 30), basis='cash_paid', data=None):
    return sourced_financing_cost(payload() if data is None else data,
        source_url=json.loads((ROOT/'source.json').read_text())['url'],
        end=end, as_of=ASOF, currency='USD', interest_basis=basis,
        debt_concept='LongTermDebt', debt_scope='reported_term_debt_including_current_maturities')


def test_fy2025_real_sources_and_hand_arithmetic():
    r = financing(date(2025, 12, 31))
    assert r['status'] == 'ok'
    assert r['annual_interest'] == 4983000000
    assert r['mean_debt'] == (Decimal(93933000000)+Decimal(94756000000))/2
    assert r['cost_of_debt_proxy'] == Decimal(4983)/Decimal('94344.5')
    assert r['accounting_etr_proxy'] == Decimal(1692)/Decimal(7458)


def test_ttm_through_june_not_halfyear_mistaken_as_annual():
    r = financing()
    assert r['status'] == 'ok'
    assert r['annual_interest'] == (4983+2506-2439)*1000000
    assert r['mean_debt'] == Decimal('94185.5')*1000000
    assert r['cost_of_debt_proxy'] == Decimal(5050)/Decimal('94185.5')
    assert r['accounting_etr_proxy'] == Decimal(1692+940-859)/Decimal(7458+3827-3763)
    assert r['start'] == date(2025, 7, 1)
    assert len(r['sources']) == 11


def test_net_interest_is_distinct_explicit_proxy():
    r = financing(basis='net_interest_expense')
    assert r['annual_interest'] == 5070000000
    assert r['cost_of_debt_proxy'] != financing()['cost_of_debt_proxy']
    assert r['interest_basis'] == 'net_interest_expense'


def test_stale_2013_over_2025_not_certified():
    data = payload()
    c = data['facts']['us-gaap']['InterestPaidNet']['units']['USD']
    data['facts']['us-gaap']['InterestPaidNet']['units']['USD'] = [r for r in c if r['end'] <= '2013-12-31']
    r = financing(date(2025, 12, 31), data=data)
    assert r['status'] == 'not_available' and r['cost_of_debt_proxy'] is None
    assert Decimal(846)/Decimal(94756) < Decimal('.009')


def test_missing_prior_ytd_or_debt_is_not_zero_or_annualized():
    for concept in ['InterestPaidNet', 'LongTermDebt']:
        data = payload()
        data['facts']['us-gaap'][concept]['units']['USD'] = [r for r in data['facts']['us-gaap'][concept]['units']['USD'] if r['end'] != '2025-06-30']
        assert financing(data=data)['status'] == 'not_available'


def assumptions():
    # Unit-test assumptions, not claims about live production market inputs.
    values = {'risk_free_rate': '.051', 'beta': '.693', 'equity_risk_premium': '.0433',
              'country_risk_premium': '0', 'market_equity': '14309630976'}
    return {k: DatedAssumption(Decimal(v), date(2026, 10, 19), date(2026, 10, 19),
                              'https://example.org/test-assumption', k,
                              'USD' if k == 'market_equity' else 'ratio' if k == 'beta' else 'decimal')
            for k, v in values.items()}


def test_wacc_hand_equation_tax_policy_explicit_and_not_cash_shield():
    r = financing()
    out = explicit_policy_wacc(r, assumptions(), as_of=ASOF, tax_policy='accounting_etr_proxy')
    e, d = Decimal(14309630976), Decimal(93959000000)
    ke = Decimal('.051')+Decimal('.693')*Decimal('.0433')
    expected = e/(e+d)*ke+d/(e+d)*(Decimal(5050)/Decimal('94185.5'))*(1-Decimal(1773)/Decimal(7522))
    assert out['wacc'] == expected
    assert out['tax_is_observed_cash_interest_shield'] is False
    assert explicit_policy_wacc(r, assumptions(), as_of=ASOF, tax_policy='')['wacc'] is None


def test_country_risk_missing_not_implicit_zero():
    inputs = assumptions()
    inputs.pop('country_risk_premium')
    assert explicit_policy_wacc(financing(), inputs, as_of=ASOF, tax_policy='accounting_etr_proxy')['wacc'] is None


def test_unsupported_end_and_future_information_rejected():
    assert financing(date(2026, 9, 29))['status'] == 'not_available'
    assert financing(date(2026, 9, 30))['status'] == 'not_available'


def test_tax_and_interest_must_share_statement_document():
    data = payload()
    for row in data['facts']['us-gaap']['IncomeTaxExpenseBenefit']['units']['USD']:
        if row['end'] == '2026-06-30':
            row['accn'] = 'different-document'
    assert financing(data=data)['status'] == 'not_available'


def test_market_future_stale_or_currency_mismatch_rejected():
    from dataclasses import replace
    for mutation in [{'observed': date(2026, 11, 5)}, {'published': date(2026, 11, 5)},
                     {'observed': date(2026, 1, 1)}, {'unit': 'EUR'}]:
        inputs = assumptions()
        inputs['market_equity'] = replace(inputs['market_equity'], **mutation)
        assert explicit_policy_wacc(financing(), inputs, as_of=ASOF, tax_policy='accounting_etr_proxy')['wacc'] is None


def test_unknown_tax_does_not_become_zero_or_full_shield():
    r = financing()
    r['accounting_etr_proxy'] = None
    assert explicit_policy_wacc(r, assumptions(), as_of=ASOF, tax_policy='accounting_etr_proxy')['wacc'] is None
    assert explicit_policy_wacc(financing(), assumptions(), as_of=ASOF, tax_policy='supplied_marginal_assumption')['wacc'] is None
