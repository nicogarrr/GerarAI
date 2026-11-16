"""No real network: catalog and billing assertions use explicit fixtures."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.llm import hy4
from app.llm.contracts import LLMRequest, Message
from app.llm.errors import ProviderDisabledError


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(hy4, '_blocked', False)


def settings(**kw):
    return SimpleNamespace(**dict(llm_enabled=True, llm_provider='opencode-go',
        opencode_go_api_key='synthetic-not-real', opencode_go_session='test', **kw))


def catalog():
    return {'data': [{'id': hy4.MODEL, 'cost': {'text': {'input': {'price': 0}, 'output': {'price': 0}}},
        'api': {'chat-completions': {'base_url': hy4.BASE}}}]}


def completion():
    return {'model': hy4.MODEL, 'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'cost': 0,
            'opencode': {'billing_source': 'go', 'list_cost': 0, 'allowance': 0}}}


def execute(catalog_body=None, body=None, status=200):
    calls = []
    def handler(request):
        calls.append((request.method, str(request.url)))
        if request.method == 'GET':
            return httpx.Response(status, json=catalog_body if catalog_body is not None else catalog())
        return httpx.Response(200, json=body if body is not None else completion())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = hy4.create_hy4_provider(settings(), client)
            with hy4.selection_scope(True):
                result = await provider.complete(LLMRequest([Message('user', 'synthetic public test')], task='chat'))
            return result
    return run, calls


def test_exact_go_catalog_then_one_inference():
    run, calls = execute()
    assert asyncio.run(run()).message.content == 'ok'
    assert calls == [('GET', hy4.CATALOG), ('POST', hy4.BASE+'/chat/completions')]


@pytest.mark.parametrize('value', [None, True, False, '0', -1, 1, float('nan'), float('inf')])
def test_non_numeric_or_nonzero_rejected(value):
    assert not hy4.zero(value)


@pytest.mark.parametrize('field,value', [('cost', 1), ('cost', None), ('billing_source', 'payg'),
    ('billing_source', None), ('list_cost', 1), ('allowance', 1)])
def test_billing_violation_latches_across_new_providers(field, value):
    body = completion()
    target = body['usage'] if field == 'cost' else body['usage']['opencode']
    target[field] = value
    run, calls = execute(body=body)
    with pytest.raises(ProviderDisabledError):
        asyncio.run(run())
    assert hy4.blocked()
    run2, next_calls = execute()
    with pytest.raises(ProviderDisabledError):
        asyncio.run(run2())
    assert not next_calls
    assert len(calls) == 2


@pytest.mark.parametrize('case', ['missing', 'priced', 'endpoint', 'broken', 'http'])
def test_bad_catalog_never_posts(case):
    doc = catalog()
    if case == 'missing': doc['data'] = []
    if case == 'priced': doc['data'][0]['cost']['text']['input']['price'] = .1
    if case == 'endpoint': doc['data'][0]['api']['chat-completions']['base_url'] = 'https://other.invalid'
    if case == 'broken': doc = {}
    run, calls = execute(catalog_body=doc, status=503 if case == 'http' else 200)
    with pytest.raises(ProviderDisabledError): asyncio.run(run())
    assert all(method == 'GET' for method, _ in calls)
    assert hy4.blocked()


@pytest.mark.parametrize('field,value', [('model', 'paid'), ('usage', None), ('usage', {'opencode': []})])
def test_malformed_metadata_latches(field, value):
    body = completion(); body[field] = value
    run, _ = execute(body=body)
    with pytest.raises(ProviderDisabledError): asyncio.run(run())
    assert hy4.blocked()


def test_egress_scope_restored_and_blocks_alternate_models():
    assert not hy4.enforce_destination('https://other.invalid', {})
    with hy4.selection_scope(True):
        assert hy4.enforce_destination(hy4.BASE+'/chat/completions', {'model': hy4.MODEL})
        with pytest.raises(ProviderDisabledError): hy4.enforce_destination(hy4.BASE+'/chat/completions', {'model': 'paid'})
        with pytest.raises(ProviderDisabledError): hy4.enforce_destination('https://other.invalid', {'model': hy4.MODEL})
    assert not hy4.enforce_destination('https://other.invalid', {})


def test_disabled_configuration():
    for key, value in [('llm_enabled', False), ('llm_provider', 'disabled'), ('opencode_go_api_key', '')]:
        config = settings(); setattr(config, key, value)
        with pytest.raises(ProviderDisabledError): hy4.create_hy4_provider(config)


def test_chat_schema_only_explicit_exact_hy4():
    from pydantic import ValidationError

    from app.schemas import ChatRequest
    assert ChatRequest(question='hola').model is None
    assert ChatRequest(question='hola', model=hy4.MODEL).model == hy4.MODEL
    with pytest.raises(ValidationError): ChatRequest(question='hola', model='hy4-flash')


@pytest.mark.parametrize('selected,trip_guard', [(True, False), (True, True), (False, False)])
def test_chat_route_wires_selection_without_debate_or_jev(monkeypatch, selected, trip_guard):
    from app.api.routes import chat as route
    from app.schemas import ChatRequest, ChatResponse
    seen = []
    class DB:
        info = {'tenant_id': 5}
        def get_bind(self): return None
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Service:
        def __init__(self, provider=None): self.provider = provider
        async def answer(self, *args, **kw):
            seen.append((self.provider, kw, hy4._selected.get()))
            if trip_guard:
                # ChatService may catch provider errors to return deterministic
                # text: outer route must still surface the cost warning.
                try: hy4.trip()
                except ProviderDisabledError: pass
            return ChatResponse(answer='ok', sources=[], model='test', confidence=1)
    marker = object()
    monkeypatch.setattr(route, 'SessionLocal', lambda **kw: DB())
    monkeypatch.setattr(route, 'ChatService', Service)
    monkeypatch.setattr(route, 'record_chat_event', lambda **kw: None)
    monkeypatch.setattr(hy4, 'create_hy4_provider', lambda *args: marker)
    payload = ChatRequest(question='hola', model=hy4.MODEL if selected else None)
    result = asyncio.run(route.chat(payload, DB()))
    if selected:
        assert seen[0][0] is marker and seen[0][2]
        assert seen[0][1]['enable_debate'] is False
        assert seen[0][1]['use_jev'] is False
    else:
        assert seen[0][0] is None and not seen[0][2]
    assert result.answer == (hy4.NOTICE if trip_guard else 'ok')
    assert not hy4._selected.get()


def test_breaker_opened_while_catalog_waits_prevents_post():
    calls = []
    async def handler(request):
        calls.append(request.method)
        # Reproduce another request tripping during our catalog await.
        try:
            hy4.trip()
        except ProviderDisabledError:
            pass
        await asyncio.sleep(0)
        return httpx.Response(200, json=catalog())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with hy4.selection_scope(True):
                provider = hy4.create_hy4_provider(settings(), client)
                await provider.complete(LLMRequest([Message('user', 'synthetic')], task='chat'))
    with pytest.raises(ProviderDisabledError):
        asyncio.run(run())
    assert calls == ['GET']


@pytest.mark.parametrize('case', ['busy', 'timeout_early', 'timeout_wall', 'error'])
def test_chat_route_admission_and_deadline_paths(monkeypatch, case):
    from app.api.routes import chat as route
    from app.schemas import ChatRequest
    class DB:
        info = {'tenant_id': 5}
        def get_bind(self): return None
    recorded = []
    monkeypatch.setattr(route, '_live_workers', route.CHAT_MAX_LIVE_WORKERS if case == 'busy' else 0)
    monkeypatch.setattr(route, 'get_settings', lambda: SimpleNamespace(chat_total_timeout_seconds=1))
    monkeypatch.setattr(route, 'record_chat_event', lambda **kw: recorded.append(kw))
    clock = iter([0, 8, 8] if case == 'timeout_wall' else [0, 0, 0])
    monkeypatch.setattr(route, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    async def fail(*args, **kwargs):
        if case == 'error': raise RuntimeError('synthetic')
        raise TimeoutError
    monkeypatch.setattr(route.anyio.to_thread, 'run_sync', fail)
    async def run(): return await route.chat(ChatRequest(question='hola'), DB())
    if case == 'error':
        with pytest.raises(RuntimeError): asyncio.run(run())
        assert recorded[0]['route'] == 'error'
    else:
        result = asyncio.run(run())
        path = result.llm_trace.get('path') or result.llm_trace.get('fallback_reason')
        assert path == {'busy': 'chat_busy', 'timeout_early': 'chat_total_deadline', 'timeout_wall': 'chat_hard_deadline'}[case]
    if case != 'busy': assert route._live_workers == 0


def test_worker_stack_and_schema_existing_boundaries():
    import threading
    from typing import Annotated

    from pydantic import TypeAdapter, ValidationError

    from app.api.routes.chat import _log_stuck_worker
    from app.schemas.api import AlertRuleOut, ThesisOut, not_blank
    from tests.test_thesis_withhold_inferred import Row
    _log_stuck_worker(threading.get_ident(), 1)
    _log_stuck_worker(None, 1)
    validator = TypeAdapter(Annotated[str, not_blank(3)])
    with pytest.raises(ValidationError): validator.validate_python(' \u200b ')
    assert validator.validate_python('hola') == 'hola'
    assert AlertRuleOut._coerce_legacy_dict(None) == {}
    assert AlertRuleOut._coerce_legacy_dict({'x': 1}) == {'x': 1}
    for raw, expected in [('mail', ['mail']), ([1, 'mail'], ['mail']), ([], ['in_app']), (None, ['in_app'])]:
        assert AlertRuleOut._coerce_legacy_channels(raw) == expected
    row = Row({'margin_of_safety_convention': 'discount_to_value_v1'})
    assert ThesisOut.model_validate(row).margin_of_safety_status == 'verified'
    row.margin_of_safety = None
    assert ThesisOut.model_validate(row).margin_of_safety_status == 'missing'
    row.valuation_withheld_reason = 'synthetic'
    row.margin_of_safety_status = 'withheld'
    row.archived_margin_of_safety = None
    assert ThesisOut.model_validate(row).valuation_withheld_reason == 'synthetic'


def test_only_one_admitted_request_per_process():
    run, calls = execute()
    assert hy4._admission.acquire(blocking=False)
    try:
        with pytest.raises(ProviderDisabledError, match='ocupado'):
            asyncio.run(run())
    finally:
        hy4._admission.release()
    assert calls == []
    assert asyncio.run(run()).message.content == 'ok'
