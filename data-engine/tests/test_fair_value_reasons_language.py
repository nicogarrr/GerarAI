"""Visible fair-value absence reasons follow the signed request language."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.core import i18n
from app.services import fair_value_service as fvs


@pytest.fixture(autouse=True)
def language_flag(monkeypatch):
    monkeypatch.setattr(i18n, 'language_enabled', lambda: True)
    token = i18n.set_language_scope('en')
    yield
    i18n.reset_language_scope(token)


def test_stale_draft_english_does_not_change_value_rules():
    today = date(2026, 11, 4)
    out = fvs.choose(None, fvs.Candidate(value=12, as_of=today-timedelta(days=181), publishable=False), today=today)
    assert out['value'] is None and out['publishable'] is False
    assert out['label'] == 'No fair value'
    assert out['reason'] == 'The latest engine valuation is an indicative draft from 181 days ago (> 180): it is withheld until recalculated.'


def test_undated_draft_is_withheld_in_english():
    out = fvs.choose(None, fvs.Candidate(value=12, as_of=None, publishable=False))
    assert out['value'] is None
    assert 'with no date' in out['reason']


def test_persisted_block_missing_inputs_and_date_in_english():
    model = SimpleNamespace(calculation_trace={'missing_inputs': ['net_debt', 'shares_outstanding']}, created_at=date(2026, 11, 4))
    out = fvs._engine_block(model)
    assert out.reason == 'The latest engine valuation from Nov 4, 2026 produced no value: missing net_debt, shares_outstanding.'
    assert out.missing_inputs == ('net_debt', 'shares_outstanding')


def test_fallback_and_live_wrapper_share_translation():
    assert fvs._insufficient_reason('', ()) == 'The latest engine valuation produced no value: the engine could not calculate a value with the available data.'
    assert fvs._insufficient_reason('raw persisted detail', ()) == 'The latest engine valuation produced no value: raw persisted detail.'


def test_flag_off_keeps_spanish_bytes(monkeypatch):
    monkeypatch.setattr(i18n, 'language_enabled', lambda: False)
    assert fvs._insufficient_reason('', ('net_debt',)) == 'La última valoración del motor no dio cifra: faltan net_debt.'
    assert fvs.choose(None, None)['label'] == 'Sin valor justo'


def test_live_cache_is_language_partitioned():
    db = SimpleNamespace(info={'tenant_id': 5})
    company = SimpleNamespace(id=42)
    english = fvs._live_cache_key(db, company)
    token = i18n.set_language_scope('es')
    try:
        spanish = fvs._live_cache_key(db, company)
    finally:
        i18n.reset_language_scope(token)
    assert ':en:' in english and ':es:' in spanish
    assert english != spanish
