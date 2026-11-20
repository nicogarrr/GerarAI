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


def test_brain_mixed_query_preserves_primary_analysis_and_adds_context(db, monkeypatch):
    from app.schemas import ChatResponse
    from app.services.chat_service import ChatService
    primary = ChatResponse(answer="MSFT DCA: nivel guardado 100", sources=[{"type": "company", "id": 12}])
    original = AsyncMock(return_value=primary)
    monkeypatch.setattr(ChatService, '_answer_impl', original)
    result = asyncio.run(ChatService().answer(db, 'MSFT DCA y VIX', 'company', 'MSFT'))
    original.assert_awaited_once()
    assert result.answer.startswith('MSFT DCA: nivel guardado 100')
    assert 'no verificada' in result.answer
    assert result.sources == [{"type": "company", "id": 12}]


def test_assistant_reader_without_ticker_has_no_fabricated_citation(db):
    from app.api.routes.research_assistant import AssistantRequest, AssistantResponse
    from app.services.research_assistant_service import answer
    payload = AssistantRequest(mode='explore', question='VIX y oportunidad extrema')
    response = AssistantResponse.model_validate(answer(db, payload))
    assert response.citations == []
    assert response.sections[-1].key == 'hypotheses'
    assert response.status == 'insufficient_data'
    assert 'Indica un ticker' in response.answer
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
    assert 'non_evidence_market_context' not in payload
    assert payload['allowed_source_ids'] == ['financial_fact:1']
    assert 'spacanpanman' not in captured[0].messages[0].content


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
    assert 'non_evidence_market_context' not in prompt
    assert 'spacanpanman' not in captured[0].messages[0].content


def test_assistant_mixed_query_preserves_review_and_dca_evidence(db, monkeypatch):
    from app.services import research_assistant_service as service
    original = {"answer": "MSFT DCA 100, revisión 27", "mode": "guide", "status": "answered",
                "review_id": 27, "sections": [{"key": "calculations", "body": "DCA 100", "citation_ids": ["dca:1"]}],
                "citations": [{"id": "dca:1"}], "missing_data": [], "writeback": False}
    seen = []
    def primary(session, payload):
        seen.append(payload)
        return original
    monkeypatch.setattr(service, '_answer', primary)
    payload = SimpleNamespace(question='MSFT DCA y VIX', review_id=27, ticker='MSFT')
    result = service.answer(db, payload)
    assert seen == [payload]
    assert result['answer'].startswith('MSFT DCA 100, revisión 27')
    assert result['review_id'] == 27 and result['citations'] == [{"id": "dca:1"}]
    assert result['sections'][0]['key'] == 'calculations'
    assert result['sections'][-1]['key'] == 'hypotheses'


def test_failed_macro_read_does_not_raise_from_assistant_synthesis(db, monkeypatch):
    from app.api.routes.research_assistant import AssistantRequest
    from app.services import research_assistant_narrative as narrative
    from app.services.budget import BudgetController
    monkeypatch.setattr(BudgetController, 'can_spend', lambda *a: True)
    def failed(_):
        raise RuntimeError('macro read failure')
    macro = AsyncMock(side_effect=AssertionError('macro must remain outside synthesis'))
    monkeypatch.setattr(narrative, 'reader_context', macro, raising=False)
    baseline = {'status': 'answered', 'answer': 'Datos MSFT originales',
                'citations': [{'id': 'fact:1', 'kind': 'financial_fact', 'excerpt': 'Ingresos 10'}]}
    provider = SimpleNamespace(name='test', complete=AsyncMock(side_effect=RuntimeError('offline fixture')))
    result = asyncio.run(narrative.synthesize(db, AssistantRequest(
        mode='explore', ticker='MSFT', question='Analiza MSFT con VIX'), baseline, provider=provider))
    assert result is baseline and result['answer'] == 'Datos MSFT originales'
    macro.assert_not_called()


def test_failed_macro_supplement_preserves_main_answer(db, monkeypatch):
    from app.schemas import ChatResponse
    from app.services.chat_service import ChatService
    monkeypatch.setattr(ChatService, '_answer_impl', AsyncMock(return_value=ChatResponse(answer='MSFT DCA 100', sources=[])))
    def failed(_):
        raise RuntimeError('macro read failure')
    monkeypatch.setattr(vix_reader, 'reader_context', failed)
    result = asyncio.run(ChatService().answer(db, 'MSFT DCA y VIX', 'company', 'MSFT'))
    assert result.answer.startswith('MSFT DCA 100')
    assert 'falló la lectura macro' in result.answer


def test_real_brain_and_assistant_dca_routes_survive_mixed_vix_query(db):
    from decimal import Decimal

    from app.api.routes.research_assistant import AssistantRequest
    from app.models.entities import Company, DcaSignalState
    from app.services.chat_service import ChatService
    from app.services.research_assistant_service import answer
    company = Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD",
                      company_type="operating", valuation_model="dcf")
    db.add(company)
    now = datetime.now(UTC)
    db.add(DcaSignalState(tenant_id=2, symbol="MSFT", level=3, status="forming", period=now.strftime("%Y-%m"),
                         signal_date=now.date(), close=Decimal("100"), currency="USD", metrics={},
                         level_prices={}, sources=[], data_source="test", params_version="nico-v1", evaluated_at=now))
    db.commit()
    result = asyncio.run(ChatService().answer(db, "¿Qué nivel DCA tiene MSFT teniendo en cuenta VIX?", "portfolio", "MSFT"))
    assert result.llm_trace['path'] == 'dca_level'
    assert 'MSFT' in result.answer and 'no verificada' in result.answer
    assistant = answer(db, AssistantRequest(mode='guide', ticker='MSFT', question='Nivel DCA MSFT y contexto VIX'))
    assert assistant['citations'] and assistant['citations'][0]['kind'] == 'market_observation'
    assert assistant['sections'][0]['key'] != 'hypotheses'
    assert 'no verificada' in assistant['answer']


def test_successful_assistant_synthesis_preserves_supplement_and_quotes_only_fact(db, monkeypatch):
    import json

    from app.api.routes.research_assistant import AssistantRequest
    from app.services import research_assistant_narrative as narrative
    from app.services.budget import BudgetController
    monkeypatch.setattr(BudgetController, 'can_spend', lambda *a: True)
    async def guarded(*a, **kw):
        return SimpleNamespace(response=SimpleNamespace(text=json.dumps({
            'sentences': [{'body': 'Ingresos 10', 'citation_ids': ['financial_fact:1']}]})))
    monkeypatch.setattr(narrative, 'complete_guarded', guarded)
    baseline = {'status': 'answered', 'answer': 'Base', 'market_context_note': 'Opinión VIX no verificada',
                'citations': [{'id': 'financial_fact:1', 'kind': 'financial_fact', 'excerpt': 'Ingresos 10'}]}
    result = asyncio.run(narrative.synthesize(db, AssistantRequest(mode='explore', ticker='MSFT',
        question='Ingresos MSFT con VIX'), baseline, provider=SimpleNamespace(name='test')))
    assert 'Ingresos 10 [financial_fact:1]' in result['answer']
    assert result['answer'].endswith('Opinión VIX no verificada')
    assert result['sections'][-1]['key'] == 'hypotheses'
    assert result['sections'][-1]['citation_ids'] == []


def test_library_macro_failure_preserves_retrieved_result(db, monkeypatch):
    from app.services import knowledge_chat
    async def primary(*a, **kw):
        return {'status': 'fragmentos', 'answers': [{'citation': 'document:7'}], 'message': 'Fragmentos reales'}
    def failed(*a):
        raise RuntimeError('macro read failure')
    monkeypatch.setattr(knowledge_chat, '_ask_library', primary)
    monkeypatch.setattr(vix_reader, 'reader_context', failed)
    result = asyncio.run(knowledge_chat.ask_library(db, 'VIX y documento'))
    assert result['answers'] == [{'citation': 'document:7'}]
    assert result['message'].startswith('Fragmentos reales')
    assert 'falló la lectura macro' in result['message']


@pytest.mark.parametrize('with_note', [False, True])
def test_synthesis_quote_callbacks_and_optional_context(db, monkeypatch, with_note):
    import json

    from app.api.routes.research_assistant import AssistantRequest
    from app.llm import LLMResponse, Message
    from app.llm.contracts import Usage
    from app.services import research_assistant_narrative as narrative
    from app.services.budget import BudgetController
    recorded = []
    monkeypatch.setattr(BudgetController, 'can_spend', lambda *a: True)
    monkeypatch.setattr(BudgetController, 'record', lambda *a: recorded.append(a))
    async def guarded(*a, **kw):
        response = LLMResponse(message=Message('assistant', json.dumps({'sentences': [
            {'body': 'Ingresos 10', 'citation_ids': ['financial_fact:1']}]})),
            model='test', provider='test', usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2))
        kw['before_retry']()
        kw['on_response'](response)
        return SimpleNamespace(response=response)
    monkeypatch.setattr(narrative, 'complete_guarded', guarded)
    baseline = {'status': 'answered', 'answer': 'Original',
                'citations': [{'id': 'financial_fact:1', 'kind': 'financial_fact', 'excerpt': 'Ingresos 10'}]}
    if with_note:
        baseline['market_context_note'] = 'VIX no verificado'
    result = asyncio.run(narrative.synthesize(db, AssistantRequest(mode='explore', ticker='MSFT',
        question='Ingresos'), baseline, provider=SimpleNamespace(name='test')))
    assert recorded
    assert bool(result['sections'][-1]['key'] == 'hypotheses') is with_note


def test_non_financial_supplement_does_not_read_macro(monkeypatch):
    monkeypatch.setattr(vix_reader, 'reader_context', lambda _: pytest.fail('unexpected macro read'))
    assert vix_reader.supplemental_note(None, 'Gracias') is None


def test_financial_answer_adds_macro_after_primary_without_vix_in_prompt(db, monkeypatch):
    from app.schemas import ChatResponse
    from app.services.chat_service import ChatService
    primary = AsyncMock(return_value=ChatResponse(answer='Microsoft: ingresos observados', sources=[]))
    monkeypatch.setattr(ChatService, '_answer_impl', primary)
    result = asyncio.run(ChatService().answer(db, 'Analiza Microsoft', 'company', 'MSFT'))
    assert result.answer.startswith('Microsoft: ingresos observados')
    assert 'no verificada' in result.answer
    assert primary.await_args.args[1] == 'Analiza Microsoft'


@pytest.mark.parametrize('question', ['Qué es un dividendo', 'Mi posición en MSFT', 'Mis impuestos 2025',
                                      'Recuerda mi idea', 'How many shares do I have?'])
def test_operational_question_does_not_get_macro_suffix(db, monkeypatch, question):
    from app.schemas import ChatResponse
    from app.services.chat_service import ChatService
    monkeypatch.setattr(ChatService, '_answer_impl', AsyncMock(return_value=ChatResponse(answer='Exact answer', sources=[])))
    assert asyncio.run(ChatService().answer(db, question, 'portfolio', 'MSFT')).answer == 'Exact answer'


def test_chat_formatting_edges_keep_missing_units_dates_and_prices_explicit():
    from app.services import chat_service as c
    assert c._fmt_value_es(None, None) == 'sin dato'
    assert c._fmt_value_es(300, 'shares') == '300 acciones'
    assert c._fmt_value_es(1000, None) == '1 mil'
    assert c._fmt_value_es(2, 'decimal') == '2'
    assert c._fmt_period_es('', 2025, 'Q2') == 'Q2 2025'
    assert c._fmt_period_es('', 2025, 'FY') == 'ejercicio 2025'
    assert c._fmt_period_es('  custom ') == 'custom'
    assert c._fmt_period_es(None) == 'periodo sin fecha'
    assert c._price_display_en(1, None) == '1.00 (currency not stated)'
    assert c._price_display_en(1, '  ') == '1.00 (currency not stated)'
    assert c._price_display_en(1, 'GBP') == '1.00 GBP'
    assert c._is_stale('bad', datetime.now(UTC)) is False
    assert c._is_stale(None, None) is False
    assert c._fmt_date_en('2026-99-01') == '2026-99-01'
    assert c._fmt_date_en('invalid') == 'invalid'


def test_risk_lead_keeps_documented_risk_separate_from_vix():
    from app.services.chat_service import _answer_lead
    arguments = dict(company=SimpleNamespace(ticker='MSFT'), facts=[], thesis=None, thesis_line=None,
                     news=[], claims=[], contradiction_claims=[], price_line=None, focus_metrics=set())
    assert _answer_lead('', **arguments) is None
    assert 'No tengo riesgos documentados' in _answer_lead('riesgo', **arguments)
    arguments.update(thesis=SimpleNamespace(valuation_risk_score=70, version=3),
                     claims=[SimpleNamespace(status='unverified')], contradiction_claims=[SimpleNamespace()])
    lead = _answer_lead('riesgo', **arguments)
    assert '1 afirmaciones contradichas' in lead and '1 afirmaciones pendientes' in lead
    assert '70/100' in lead


def test_rag_company_evidence_rejects_cross_tenant_invalid_duplicate_and_mismatched_hits(db, monkeypatch):
    from app.models.entities import Company, Document, DocumentChunk
    from app.services import rag
    from app.services.chat_service import ChatService
    monkeypatch.setenv('CAVAAI_ENABLE_VECTOR_CHAT', '1')
    company = Company(ticker='MSFT', name='Microsoft', exchange='NASDAQ', currency='USD',
                      company_type='operating', valuation_model='dcf')
    db.add(company)
    db.flush()
    document = Document(tenant_id=2, company_id=company.id, title='Filing', source_type='company_ir')
    db.add(document)
    db.flush()
    chunks = []
    for text, point in [('Revenue 10', 'point1'), ('', 'point2'), ('Debt 2', None), ('Cash 3', 'point4')]:
        chunk = DocumentChunk(tenant_id=2, document_id=document.id, text=text, chunk_index=len(chunks),
                              qdrant_point_id=point)
        db.add(chunk)
        chunks.append(chunk)
    db.flush()
    hits = [{'entity_type': 'document_chunk', 'entity_id': c.id, 'point_id': c.qdrant_point_id} for c in chunks]
    hits[-1]['point_id'] = 'wrong'
    hits += [hits[0], {'entity_type': 'other', 'entity_id': chunks[0].id},
             {'entity_type': 'document_chunk', 'entity_id': 'bad'},
             {'entity_type': 'document_chunk', 'entity_id': 999999, 'point_id': 'ghost'}]
    monkeypatch.setattr(rag, 'RAGIndex', lambda: SimpleNamespace(search=lambda *a, **kw: hits))
    service = ChatService()
    assert [r['entity_id'] for r in service._rag_chunks(db, 'Revenue', company)] == [chunks[0].id]
    assert [r['entity_id'] for r in service._rag_chunks(db, 'Revenue', None)] == [chunks[0].id]
    db.info['tenant_id'] = None
    assert service._rag_chunks(db, 'Revenue', company) == []
    db.info['tenant_id'] = 2
    monkeypatch.setattr(rag, 'RAGIndex', lambda: SimpleNamespace(search=lambda *a, **kw: []))
    assert service._rag_chunks(db, 'Revenue', company) == []
    def failed():
        raise RuntimeError('vector unavailable')
    monkeypatch.setattr(rag, 'RAGIndex', failed)
    assert service._rag_chunks(db, 'Revenue', company) == []
