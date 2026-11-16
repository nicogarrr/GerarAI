import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.routes import research_assistant as route
from app.llm import hy4
from app.llm.errors import ProviderDisabledError


def baseline():
    return dict(mode='guide', status='answered', answer='Cited baseline', sections=[], citations=[],
                missing_data=[], suggested_next_steps=[], review_id=None)


@pytest.mark.parametrize('selected,error', [(False, None), (True, None), (True, 'cost'), (True, 'config')])
def test_route_injects_only_explicit_hy4_and_warns_on_cut(monkeypatch, selected, error):
    monkeypatch.setattr(hy4, '_blocked', False)
    calls = []
    marker = object()
    def create(*args):
        if error == 'config': raise ProviderDisabledError('disabled')
        return marker
    async def synthesize(db, payload, result, **kw):
        calls.append((kw.get('provider'), hy4._selected.get()))
        if error == 'cost':
            try: hy4.trip()
            except ProviderDisabledError: pass
        return result
    async def thread(fn, *args): return fn(*args)
    monkeypatch.setattr(route, 'run_in_threadpool', thread)
    monkeypatch.setattr(route, 'resolve_page_context', lambda *args: None)
    monkeypatch.setattr(route, 'answer', lambda *args: baseline())
    monkeypatch.setattr(route, 'synthesize', synthesize)
    monkeypatch.setattr(hy4, 'create_hy4_provider', create)
    payload = route.AssistantRequest(mode='guide', ticker='TEST', question='synthetic', model=hy4.MODEL if selected else None)
    response = asyncio.run(route.research_assistant(payload, object()))
    assert not hy4._selected.get()
    if error:
        assert hy4.NOTICE in response.answer and hy4.NOTICE in response.missing_data
        assert 'Cited baseline' in response.answer
    else:
        assert calls == [(marker if selected else None, selected)]
        assert response.answer == 'Cited baseline'


def test_schema_rejects_other_models():
    with pytest.raises(ValidationError):
        route.AssistantRequest(mode='guide', ticker='TEST', question='synthetic', model='paid')


def test_page_ticker_and_lookup_boundaries(monkeypatch):
    from fastapi import HTTPException
    async def thread(fn, *args): return fn(*args)
    monkeypatch.setattr(route, 'run_in_threadpool', thread)
    context = SimpleNamespace(company=SimpleNamespace(ticker='TEST'), echo=lambda: {'ticker':'TEST'})
    monkeypatch.setattr(route, 'resolve_page_context', lambda *args: context)
    def missing(db, payload):
        assert payload.ticker == 'TEST'
        raise LookupError('missing')
    monkeypatch.setattr(route, 'answer', missing)
    payload = route.AssistantRequest(mode='explore', question='synthetic')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.research_assistant(payload, object()))
    assert exc.value.status_code == 404
    with pytest.raises(ValidationError):
        route.AssistantRequest(mode='explore', question='synthetic', review_id=1)
    monkeypatch.setattr(route, 'guide_context', lambda *args: dict(ticker='TEST', review_id=None, open_reviews=[], latest_news=[], missing_data=[]))
    assert route.research_guide_context('TEST', object()).ticker == 'TEST'
