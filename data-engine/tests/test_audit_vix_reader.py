import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, ResearchReview


@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info['tenant_id']=2
        # Fixture completion: the original requested a company and review
        # without creating either, so the correct old route returned 404.
        company = Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD",
                          company_type="operating", valuation_model="dcf")
        session.add(company)
        session.flush()
        session.add(ResearchReview(id=999, tenant_id=2, company_id=company.id,
                                  review_type="news", title="Selected review",
                                  summary="Selected review content", status="open"))
        session.commit()
        yield session
    engine.dispose()


def test_mixed_company_question_must_not_lose_selected_review(db):
    from app.api.routes.research_assistant import AssistantRequest
    from app.services.research_assistant_service import answer
    payload=AssistantRequest(mode='explore',ticker='MSFT',review_id=999,question='Resume los ingresos de MSFT de mi review seleccionada y ten en cuenta el VIX')
    result=answer(db,payload)
    assert result.get('review_id')==999 or result['status']!='answered', result


def test_macro_read_failure_preserves_company_synthesis_baseline(db,monkeypatch):
    from app.api.routes.research_assistant import AssistantRequest
    from app.services import research_assistant_narrative as target
    from app.services.budget import BudgetController
    def broken(_): raise RuntimeError('macro unavailable fixture')
    monkeypatch.setattr(target,'reader_context',broken)
    monkeypatch.setattr(BudgetController,'can_spend',lambda *a:True)
    baseline={'status':'answered','citations':[{'id':'financial_fact:1','kind':'financial_fact','excerpt':'Ingresos 10'}],'answer':'Ingresos 10'}
    provider=SimpleNamespace(name='test',complete=AsyncMock(side_effect=RuntimeError('offline')))
    payload=AssistantRequest(mode='explore',ticker='MSFT',question='Resume los ingresos de MSFT')
    assert asyncio.run(target.synthesize(db,payload,baseline,provider=provider)) is baseline
