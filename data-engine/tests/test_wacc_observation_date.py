"""A retrieval date cannot replace the economic observation's missing date."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.entities import Document, FinancialFact
from app.services import wacc_input_service
from app.services.wacc_input_service import WaccInputService
from tests.test_wacc_input_service import (
    _company,
    _patch_fred,
    _patch_no_yfinance,
    _run,
    _StubFred,
    db,  # noqa: F401
)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 14, 12, tzinfo=UTC)


@pytest.mark.parametrize('reported_date', [None, '', 'not-a-date', '2026-02-30', '2026-11-15', '2099-01-01'])
def test_invalid_missing_or_future_observation_never_becomes_today(db, monkeypatch, reported_date):
    _patch_no_yfinance(monkeypatch)
    monkeypatch.setattr(wacc_input_service, 'datetime', Clock)
    stub = _StubFred()
    stub.observations = [{'date':reported_date, 'value':'4.25'}]
    _patch_fred(monkeypatch, stub)
    result = _run(WaccInputService().refresh(db, _company(db)))
    assert db.scalar(select(FinancialFact).where(FinancialFact.metric == 'risk_free_rate')) is None
    assert db.scalar(select(Document).where(Document.source_type == 'FRED')) is None
    assert 'risk_free_rate' in result['missing']


@pytest.mark.parametrize('configured', [False, True])
def test_skips_unusable_newer_dates_and_preserves_real_observation_date(db, monkeypatch, configured):
    _patch_no_yfinance(monkeypatch)
    monkeypatch.setattr(wacc_input_service, 'datetime', Clock)
    stub = _StubFred(configured=configured)
    points = [{'date':'2026-11-15','value':'9'}, {'value':'8'}, {'date':'2026-11-12','value':'4.25'}]
    stub.observations = stub.csv_observations = points
    _patch_fred(monkeypatch, stub)
    _run(WaccInputService().refresh(db, _company(db)))
    fact = db.scalar(select(FinancialFact).where(FinancialFact.metric == 'risk_free_rate'))
    document = db.scalar(select(Document).where(Document.source_type == 'FRED'))
    assert fact.period == '2026-11-12'
    assert fact.value == Decimal('0.0425')
    assert document.metadata_['date'] == fact.period
    assert document.metadata_['via'] == ('api_key' if configured else 'fredgraph_csv')
