"""Regression fixtures reproduce displayed inputs, not a claim of corrected yields."""
from decimal import Decimal

import pytest

from app.services.deep_value_service import find_deep_value
from app.services.valuation_metrics_service import STATUS_DISAGREE
from tests.test_deep_value import TODAY, _db, _seed


@pytest.mark.parametrize('ticker,yld', [('PARA', '96.154'), ('ELME', '34.8')])
def test_incident_yields_remain_visible_but_have_no_score(ticker, yld):
    db = _db()
    _seed(db, ticker, pb='0.001', yld=yld, yield_status=STATUS_DISAGREE,
          y_trace={'desacuerdo_fuentes': True, 'yield_extremo_revisar': True})
    (row,) = find_deep_value(db, today=TODAY)
    assert row.score is None
    assert row.review_reasons == ['yield_sources_disagree', 'yield_extreme']
    assert row.dividend_yield == Decimal(yld)


def test_legitimate_high_dividend_still_scores_and_ranks_before_pending():
    db = _db()
    _seed(db, 'HIGH12', pb='0.7', yld='0.12')
    _seed(db, 'PARA', pb='0.001', yld='96.154')
    rows = find_deep_value(db, today=TODAY)
    assert [r.ticker for r in rows] == ['HIGH12', 'PARA']
    assert rows[0].score == pytest.approx(58)
    assert rows[0].review_reasons == []
    assert rows[1].score is None


@pytest.mark.parametrize('yld,pending', [('0.25', False), ('0.250001', True)])
def test_existing_extreme_threshold_is_strict_25_percent_without_trace(yld, pending):
    db = _db()
    _seed(db, 'BOUND', pb='0.5', yld=yld)
    (row,) = find_deep_value(db, today=TODAY)
    assert (row.score is None) is pending
    assert row.yield_extremo_revisar is pending


@pytest.mark.parametrize('status,trace', [
    (STATUS_DISAGREE, {}),
    ('ok', {'desacuerdo_fuentes': True}),
    ('ok', {'finnhub_yield_indicated': '0.02'}),
])
def test_disagreement_cannot_score_even_if_trace_flags_are_incomplete(status, trace):
    db = _db()
    _seed(db, 'DIS', pb='0.5', yld='0.08', yield_status=status, y_trace=trace)
    (row,) = find_deep_value(db, today=TODAY)
    assert row.score is None
    assert row.desacuerdo_fuentes is True
    assert row.review_reasons == ['yield_sources_disagree']


def test_trustworthy_yield_keeps_score_and_trace():
    db = _db()
    _seed(db, 'SAME', pb='0.5', yld='0.10', y_trace={'finnhub_yield_indicated': '0.09'})
    (row,) = find_deep_value(db, today=TODAY)
    assert row.score == pytest.approx(70)
    assert row.review_reasons == []  # 10% relative disagreement is allowed; greater is not


def test_pending_does_not_take_ranked_limit_and_stays_ticker_sorted():
    db = _db()
    _seed(db, 'PARA', pb='0.001', yld='96.154')
    _seed(db, 'ELME', pb='0.002', yld='34.8')
    _seed(db, 'HIGH12', pb='0.7', yld='0.12')
    rows = find_deep_value(db, today=TODAY, limit=1)
    assert [r.ticker for r in rows] == ['HIGH12', 'ELME']
    assert rows[1].score is None  # one item per independently bounded section


def test_disputed_yield_does_not_satisfy_minimum_dividend_filter():
    db = _db()
    _seed(db, 'DIS', pb='0.1', yld='0.08', yield_status=STATUS_DISAGREE)
    rows = find_deep_value(db, today=TODAY, yield_min=Decimal('0.05'))
    assert len(rows) == 1  # visible to explain why it is not ranked
    assert rows[0].score is None


@pytest.mark.parametrize('trace,reason', [
    ({'split_factor': '0.005'}, 'pb_split_basis_unverified'),
    ({'split_factor': '0'}, 'pb_split_factor_invalid'),
    ({'split_factor': 'bad'}, 'pb_split_factor_invalid'),
    ({'split_factor': 'NaN'}, 'pb_split_factor_invalid'),
    ({'price': '2', 'total_equity': '100', 'shares_diluted': '10', 'split_factor': '1'}, 'pb_inputs_inconsistent'),
])
def test_unverified_split_basis_or_inconsistent_pb_never_scores(trace, reason):
    db = _db()
    _seed(db, 'BASIS', pb='0.5', yld='0.08', pb_trace=trace)
    (row,) = find_deep_value(db, today=TODAY)
    assert row.score is None
    assert reason in row.review_reasons


def test_verified_split_basis_is_not_rejected_just_because_pb_is_small():
    db = _db()
    _seed(db, 'VALIDSPLIT', pb='0.001', yld='0.12', pb_trace={
        'split_factor': '0.005', 'shares_period': '2025-12-31:FY',
        'shares_filed': '2026-03-01', 'split_basis': 'fact_split_factor_filed_aware',
        'price': '2', 'total_equity': '100', 'shares_diluted': '10',
    })
    (row,) = find_deep_value(db, today=TODAY)
    assert row.score is not None
    assert row.review_reasons == []


@pytest.mark.parametrize('kind', ['liquidating', 'special', 'return_of_capital'])
def test_nonrecurring_distribution_is_quarantined_only_with_structured_evidence(kind):
    db = _db()
    _seed(db, 'EVENT', pb='0.5', yld='0.08', y_trace={
        'dividend_events': [{'date': TODAY.isoformat(), 'amount': '1', 'distribution_type': kind}]
    })
    (row,) = find_deep_value(db, today=TODAY)
    assert row.score is None
    assert 'dividend_non_recurring' in row.review_reasons


@pytest.mark.parametrize('price_day', ['2026-10-01', '2026-11-01', 'unknown'])
def test_fresh_metric_does_not_refresh_an_old_future_or_malformed_source_price(price_day):
    db = _db()
    _seed(db, 'PRICE', pb='0.5', yld='0.08', pb_trace={'price_date': price_day})
    (row,) = find_deep_value(db, today=TODAY)
    assert row.score is None
    assert 'pb_price_stale_or_invalid' in row.review_reasons


def test_pb_status_is_a_ranking_gate():
    from sqlalchemy import select

    from app.models import CalculatedMetric
    db = _db()
    company = _seed(db, 'STATUS', pb='0.5', yld='0.08')
    row = db.scalar(select(CalculatedMetric).where(
        CalculatedMetric.company_id == company.id, CalculatedMetric.metric == 'price_to_book'))
    row.status = 'pendiente'
    (result,) = find_deep_value(db, today=TODAY)
    assert result.score is None
    assert result.review_reasons == ['pb_status_unverified']


def test_ingest_preserves_structured_distribution_evidence():
    from app.services.valuation_metrics_service import ttm_dividend_per_share
    total, used = ttm_dividend_per_share([
        {'date': TODAY.isoformat(), 'amount': '1.74', 'distribution_type': 'liquidating'}
    ], TODAY)
    assert total == Decimal('1.74')
    assert used[0]['distribution_type'] == 'liquidating'
