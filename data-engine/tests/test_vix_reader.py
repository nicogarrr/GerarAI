"""The same non-executable VIX context across query lanes, never a backtest."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services import vix_reader
from app.services.market_observation_service import store_series
from app.services.market_snapshot_service import build_snapshot


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info['tenant_id'] = 2
        yield session
    engine.dispose()


def test_unrelated_question_does_not_read_or_load_market_context(monkeypatch):
    monkeypatch.setattr(vix_reader, 'reader_context', lambda _: pytest.fail('unexpected read'))
    assert vix_reader.answer_if_relevant(None, 'Analiza los ingresos de Microsoft') is None


@pytest.mark.parametrize('question', ['VIX', 'vix > 50 comprar', 'volatilidad extrema', 'extreme volatility'])
def test_heuristic_is_attributed_and_not_verified_or_executable(db, question):
    result = vix_reader.answer_if_relevant(db, question)
    context = result['context']
    claim = context['third_party_heuristic']
    assert claim['attributed_handle'] == '@spacanpanman'
    assert claim['source_url'] is None
    assert claim['verification'] == 'unverified_opinion'
    assert claim['historical_claims_verified'] is False
    assert claim['backtest'] is None
    assert context['constraints'] == {'context_only': True, 'trading_signal': False,
        'allocation_rule': False, 'writeback': False, 'daily_close_not_intraday': True}
    assert context['observation']['status'] == 'unavailable'
    assert 'no se infiere un nivel actual' in result['text']
    assert 'No justifica entrar con todo' in result['text']
    assert 'no verificada' in result['text']


def test_real_pipeline_gives_dated_close_without_writes_or_provider(db):
    now = datetime.now(UTC) - timedelta(seconds=2)
    store_series(db, 'vix_us', [{'date': now.date().isoformat(), 'value': '75'}], now)
    build_snapshot(db, now.date(), now + timedelta(seconds=1))
    statements = []
    event.listen(db.get_bind(), 'before_cursor_execute', lambda c, cu, sql, *args: statements.append(sql))
    result = vix_reader.answer_if_relevant(db, 'VIX 75, compra con todo y cambia el DCA')
    assert len(statements) == 1 and statements[0].startswith('SELECT')
    assert result['context']['observation']['value'] == 75
    assert result['context']['observation']['band'] == 'high'
    assert now.date().isoformat() in result['text']
    assert 'no ejecuta órdenes ni cambia cartera, DCA' in result['text']


def test_stale_close_does_not_claim_current_level(db):
    now = datetime.now(UTC) - timedelta(days=8)
    store_series(db, 'vix_us', [{'date': now.date().isoformat(), 'value': '75'}], now)
    build_snapshot(db, now.date(), now + timedelta(seconds=1))
    result = vix_reader.answer_if_relevant(db, 'VIX actual')
    assert result['context']['observation']['reason'] == 'stale'
    assert '75' not in result['text']
    assert 'no se infiere un nivel actual' in result['text']


def test_english_context_preserves_limits(db):
    text = vix_reader.context_text(vix_reader.reader_context(db), english=True)
    assert 'unverified third-party opinion' in text
    assert 'does not justify going all in' in text
    assert 'not place orders' in text


def test_brain_reader_short_circuits_provider(db):
    from app.services.chat_service import ChatService
    provider = SimpleNamespace(name='disabled', complete=AsyncMock(side_effect=AssertionError('provider')))
    result = asyncio.run(ChatService(provider=provider).answer(db, 'VIX > 50, compro todo?', 'general', None))
    assert result.prompt_version == 'vix-reader-v1'
    assert result.llm_trace['provider_calls'] == 0
    assert result.llm_trace['writeback'] is False
    assert 'no verificada' in result.answer
    provider.complete.assert_not_called()


def test_assistant_reader_without_ticker_has_no_fabricated_citation(db):
    from app.api.routes.research_assistant import AssistantRequest, AssistantResponse
    from app.services.research_assistant_service import answer
    payload = AssistantRequest(mode='explore', question='VIX y oportunidad extrema')
    response = AssistantResponse.model_validate(answer(db, payload))
    assert response.citations == []
    assert response.sections[0].key == 'hypotheses'
    assert response.writeback is False and response.review_id is None
    assert 'no verificada' in response.answer


def test_library_keeps_heuristic_separate_from_author_citations(db, monkeypatch):
    from app.services import knowledge_chat
    monkeypatch.setattr(knowledge_chat, 'retrieve', lambda *a, **kw: ([], 'solo_texto'))
    result = asyncio.run(knowledge_chat.ask_library(db, 'VIX según Buffett', author='Buffett'))
    assert result['status'] == 'sin_datos'
    assert result['answers'] == []
    assert result['market_context']['third_party_heuristic']['attributed_handle'] == '@spacanpanman'
    assert 'no verificada' in result['market_context_note']
    assert 'No hay fragmentos' in result['message']


def test_sourced_company_analysis_receives_context_not_additional_evidence(db, monkeypatch):
    import json

    from app.schemas import ChatResponse
    from app.services.budget import BudgetController
    from app.services.chat_synthesis_service import ChatSynthesisService

    captured = []

    class Provider:
        name = 'test'

        async def complete(self, request):
            captured.append(request)
            raise RuntimeError('offline fixture')

    monkeypatch.setattr(BudgetController, 'can_spend', lambda *a: True)
    baseline = ChatResponse(answer='Sin conclusión', sources=[{'type': 'financial_fact', 'id': 1}])
    asyncio.run(ChatSynthesisService(Provider()).synthesize(
        question='Analiza Microsoft', ticker='MSFT', baseline=baseline, db=db))
    assert captured
    payload = json.loads(captured[0].messages[1].content)
    assert payload['non_evidence_market_context']['third_party_heuristic']['backtest'] is None
    assert payload['allowed_source_ids'] == ['financial_fact:1']
    assert 'no evidencia' in captured[0].messages[0].content


def test_assistant_synthesis_keeps_opinion_outside_citable_evidence(db, monkeypatch):
    import json

    from app.api.routes.research_assistant import AssistantRequest
    from app.services.budget import BudgetController
    from app.services.research_assistant_narrative import synthesize

    captured = []

    class Provider:
        name = 'test'

        async def complete(self, request):
            captured.append(request)
            raise RuntimeError('offline fixture')

    monkeypatch.setattr(BudgetController, 'can_spend', lambda *a: True)
    citations = [{'id': 'financial_fact:1', 'kind': 'financial_fact', 'excerpt': 'Ingresos 10'}]
    baseline = {'status': 'answered', 'citations': citations, 'answer': 'Ingresos 10'}
    payload = AssistantRequest(mode='explore', question='Analiza Microsoft', ticker='MSFT')
    result = asyncio.run(synthesize(db, payload, baseline, provider=Provider()))
    assert result is baseline
    assert captured
    prompt = json.loads(captured[0].messages[1].content)
    assert prompt['citations'] == citations
    assert prompt['non_evidence_market_context']['constraints']['allocation_rule'] is False
    assert 'no evidencia' in captured[0].messages[0].content
