from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import propicks
from app.services import propicks_snapshot_service


def test_freeze_snapshot_success_and_empty(monkeypatch):
    monkeypatch.setattr(propicks_snapshot_service, 'freeze_monthly_snapshot', lambda db: None)
    with pytest.raises(HTTPException) as exc:
        propicks.freeze_snapshot(db=object())
    assert exc.value.status_code == 409
    monkeypatch.setattr(propicks_snapshot_service, 'freeze_monthly_snapshot', lambda db: SimpleNamespace(month='2026-11', as_of='2026-11-15', passed_count=2))
    assert propicks.freeze_snapshot(db=object())['passed_count'] == 2


@pytest.mark.parametrize('enabled', [True, False])
def test_review_route_with_mocked_free_provider_only(monkeypatch, enabled):
    import asyncio

    from app import llm
    from app.services import llm_proposal_runner, propicks_review_service
    from app.services.budget import BudgetController

    gem = SimpleNamespace(ticker='QA', name='Fixture', score=50, reasons=[], price=10, price_date='2026-11-15', market_cap=100)
    monkeypatch.setattr(propicks, 'run_funnel', lambda *args, **kwargs: ([], {}))
    monkeypatch.setattr(propicks, 'find_gems', lambda *args, **kwargs: [gem])
    monkeypatch.setattr(llm, 'create_llm_provider', lambda: SimpleNamespace(name='mock' if enabled else 'disabled'))
    monkeypatch.setattr(llm_proposal_runner, 'paid_model_risk', lambda provider: None)
    monkeypatch.setattr(BudgetController, 'can_spend', lambda *args: True)
    monkeypatch.setattr(propicks_review_service, 'log_reviews', lambda *args, **kwargs: None)

    async def reviews(provider, candidates, **kwargs):
        return [propicks_review_service.Review('QA', propicks_review_service.NO_REVIEW, reject_reason='fixture')]
    monkeypatch.setattr(propicks_review_service, 'review_shortlist', reviews)
    db = SimpleNamespace(get_bind=lambda: None, info={}, commit=lambda: None)
    result = asyncio.run(propicks.review_gems(limit=1, db=db))
    assert result[0]['ticker'] == 'QA'
