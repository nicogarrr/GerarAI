import gzip
import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.valuation.coherent_debt import BalanceOperand, coherent_debt_bridge, sec_balance_operands

ROOT = Path(__file__).parent / 'fixtures/sec_debt'
END = date(2026, 9, 30)
ASOF = date(2026, 11, 4)


def original(name):
    source = json.loads((ROOT / f'{name}.source.json').read_text())
    data = gzip.decompress((ROOT / f'{name}.json.gz').read_bytes())
    assert hashlib.sha256(data).hexdigest() == source['sha256']
    return sec_balance_operands(json.loads(data), source_url=source['url'], as_of=ASOF)


def bridge(facts, **kwargs):
    return coherent_debt_bridge(facts, end=END, as_of=ASOF, currency='USD', cash_policy=kwargs.pop('cash_policy', 'cash_only'), **kwargs)


def operand(concept, value, **kwargs):
    return BalanceOperand(concept, Decimal(value), 'USD', END, date(2026, 11, 3),
                          'filing', 'https://www.sec.gov/example', concept, **kwargs)


def test_unh_real_sec_debtcurrent_not_longtermdebtcurrent():
    facts = original('unh')
    result = bridge(facts)
    assert result['total_debt'] == 74331000000
    assert result['current_debt'] == 5617000000
    assert result['net_debt'] == 48486000000
    assert bridge(facts, cash_policy='cash_plus_current_securities')['net_debt'] == 45782000000
    assert {f.document for f in result['components']} == {'0000731766-26-000266'}
    assert all(f.end == END for f in result['components'])


def test_unh_missing_current_is_not_total_debt():
    facts = [f for f in original('unh') if f.concept != 'DebtCurrent']
    assert bridge(facts)['total_debt'] is None
    assert bridge(facts)['net_debt'] is None


def test_pltr_absent_debt_concept_not_explicit_zero():
    facts = original('pltr')
    result = bridge(facts, cash_policy='cash_plus_current_securities')
    assert result['total_debt'] is None and result['net_debt'] is None
    assert any(f.value == 6942117000 for f in result['components'])
    assert not any('RestrictedCash' in f.concept for f in result['components'])


def test_explicit_official_zero_not_absence_and_policy_separate():
    facts = [operand('DebtLongtermAndShorttermCombinedAmount', '0'),
             operand('CashAndCashEquivalentsAtCarryingValue', '100'),
             operand('MarketableSecuritiesCurrent', '200'),
             operand('RestrictedCashAndCashEquivalentsAtCarryingValue', '50')]
    assert bridge(facts)['net_debt'] == -100
    assert bridge(facts, cash_policy='cash_plus_current_securities')['net_debt'] == -300
    assert bridge(facts[1:])['net_debt'] is None
    assert bridge([replace(f, official=False) for f in facts])['net_debt'] is None


def test_source_period_and_currency_cannot_be_mixed_or_backfilled():
    facts = [operand('DebtCurrent', '5'), operand('LongTermDebtNoncurrent', '68'),
             operand('CashAndCashEquivalentsAtCarryingValue', '25')]
    assert bridge(facts)['net_debt'] == 48
    for mutation in [{'end': date(2025, 12, 31)}, {'document': 'other'}, {'currency': 'EUR'},
                     {'filed': date(2026, 11, 5)}]:
        changed = facts[:2] + [replace(facts[2], **mutation)]
        assert bridge(changed)['net_debt'] is None


def test_aggregate_not_added_to_current_and_conflict_fails_closed():
    facts = [operand('DebtLongtermAndShorttermCombinedAmount', '73'),
             operand('DebtCurrent', '5'), operand('LongTermDebtNoncurrent', '68'),
             operand('CashAndCashEquivalentsAtCarryingValue', '25')]
    assert bridge(facts)['total_debt'] == 73
    assert bridge([replace(facts[0], value=Decimal(74)), *facts[1:]])['status'] == 'conflict'
    assert bridge([*facts, replace(facts[0], value=Decimal(72))])['status'] == 'conflict'


def test_cash_securities_missing_is_not_zero_and_alias_conflict():
    facts = [operand('DebtLongtermAndShorttermCombinedAmount', '10'),
             operand('CashAndCashEquivalentsAtCarryingValue', '2')]
    assert bridge(facts)['net_debt'] == 8
    assert bridge(facts, cash_policy='cash_plus_current_securities')['net_debt'] is None
    facts += [operand('ShortTermInvestments', '3'), operand('MarketableSecuritiesCurrent', '4')]
    assert bridge(facts, cash_policy='cash_plus_current_securities')['status'] == 'conflict'


def test_unh_point_in_time_before_q3_filing_no_future_fact():
    result = coherent_debt_bridge(original('unh'), end=END, as_of=date(2026, 11, 2),
                                   currency='USD', cash_policy='cash_only')
    assert result['net_debt'] is None


def test_chtr_cannot_reuse_previous_quarter_or_ytd_as_q3():
    from app.valuation.coherent_debt import exact_sec_cashflow
    source = json.loads((ROOT / 'chtr.source.json').read_text())
    raw = gzip.decompress((ROOT / 'chtr.json.gz').read_bytes())
    assert hashlib.sha256(raw).hexdigest() == source['sha256']
    payload = json.loads(raw)
    q3 = exact_sec_cashflow(payload, start=date(2026, 7, 1), end=END, as_of=ASOF,
                            currency='USD', source_url=source['url'])
    assert q3['status'] == 'not_available' and q3['facts'] == {}
    assert q3['latest_available_end'] == date(2026, 6, 30)
    ytd = exact_sec_cashflow(payload, start=date(2026, 1, 1), end=date(2026, 6, 30),
                             as_of=ASOF, currency='USD', source_url=source['url'])
    assert ytd['status'] == 'ok'
    assert ytd['facts']['operating_cash_flow']['value'] == 8229000000


def test_old_direct_net_debt_never_overrides_new_exact_components():
    facts = original('unh')
    old = operand('net_debt', '10')
    old = replace(old, end=date(2025, 12, 31), filed=date(2026, 2, 1))
    assert bridge([old, *facts])['net_debt'] == 48486000000
    assert bridge([old])['net_debt'] is None


def test_longterm_current_alias_never_double_counts_debtcurrent():
    facts = [operand('DebtCurrent', '5'), operand('LongTermDebtCurrent', '3'),
             operand('ShortTermBorrowings', '2'), operand('LongTermDebtNoncurrent', '68'),
             operand('CashAndCashEquivalentsAtCarryingValue', '25')]
    assert bridge(facts)['total_debt'] == 73


def test_nonfinite_negative_and_mixed_latest_document_rejected():
    facts = [operand('DebtLongtermAndShorttermCombinedAmount', '10'),
             operand('CashAndCashEquivalentsAtCarryingValue', '2')]
    for invalid in ['NaN', 'Infinity', '-1']:
        assert bridge([replace(facts[0], value=Decimal(invalid)), facts[1]])['status'] == 'conflict'
    assert bridge([facts[0], replace(facts[1], document='other')])['status'] == 'conflict'
