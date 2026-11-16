import asyncio

import pytest
from pydantic import ValidationError

from app.api.routes import knowledge as route
from app.llm import hy4
from app.llm.errors import ProviderDisabledError
from app.services import knowledge_chat


@pytest.mark.parametrize('model,error', [(None,None), (hy4.MODEL,None), (hy4.MODEL,'billing'), (hy4.MODEL,'config')])
def test_chat_library_selection_scope(monkeypatch, model, error):
    monkeypatch.setattr(hy4, '_blocked', False)
    marker = object()
    calls = []
    def create(*args):
        if error == 'config': raise ProviderDisabledError('disabled')
        return marker
    async def ask(db, **kwargs):
        calls.append((kwargs, hy4._selected.get()))
        if error == 'billing':
            try: hy4.trip()
            except ProviderDisabledError: pass
        return {'status':'ok','answers':[]}
    async def thread(fn, *args): return fn(*args)
    monkeypatch.setattr(route, 'run_in_threadpool', thread)
    monkeypatch.setattr(route, 'resolve_page_context', lambda *args: None)
    monkeypatch.setattr(knowledge_chat, 'ask_library', ask)
    monkeypatch.setattr(hy4, 'create_hy4_provider', create)
    result=asyncio.run(route.chat_library(route.LibraryQuestion(question='synthetic',model=model), object()))
    if error: assert result['message'] == hy4.NOTICE
    elif model:
        assert calls[0][0]['provider'] is marker and calls[0][1]
    else:
        assert 'provider' not in calls[0][0] and not calls[0][1]
    assert not hy4._selected.get()
    assert result['context'] is None


def test_library_model_exact_schema():
    with pytest.raises(ValidationError): route.LibraryQuestion(question='synthetic', model='paid')


def test_legacy_library_request_model_is_pinned_to_hy4():
    from types import SimpleNamespace

    from app.llm.contracts import LLMRequest, Message
    provider=hy4.create_hy4_provider(SimpleNamespace(llm_enabled=True,llm_provider='opencode-go',
        opencode_go_api_key='synthetic',opencode_go_session='test'))
    assert provider.model_router.resolve(LLMRequest([Message('user','synthetic')],task='chat',model='space-bunny-free')) == hy4.MODEL


@pytest.mark.parametrize('kind,lang,url', [('invalid','en',None),('personal_note','xx',None),('personal_note','en','not-a-url'),('personal_note','en','https://example.org/'+('x'*1000))])
def test_upload_metadata_invalid_boundaries(kind,lang,url):
    with pytest.raises(ValueError): route.validate_upload_metadata(document_type=kind,language=lang,source_url=url)


def test_upload_metadata_good():
    assert route.validate_upload_metadata(document_type='personal_note',language=' ES ',source_url='https://example.org')[1:] == ('es','https://example.org/')


@pytest.mark.parametrize('failure', [None, 'value', 'provider'])
def test_upload_route_read_and_error_handling(monkeypatch, failure):
    from io import BytesIO

    from fastapi import HTTPException, UploadFile
    async def thread(fn,*args,**kw): return fn(*args,**kw)
    class Service:
        def ingest_bytes(self,*args,**kw):
            assert kw['content']==b'public fixture'
            if failure=='value': raise ValueError('synthetic')
            if failure=='provider': raise RuntimeError('synthetic')
            return {'id':1}
    monkeypatch.setattr(route,'run_in_threadpool',thread)
    monkeypatch.setattr(route,'KnowledgeLibraryService',Service)
    async def run(): return await route.upload_document(title='synthetic',document_type='personal_note',collection_id=None,author=None,source_url=None,publication_date=None,language='en',ticker=None,file=UploadFile(file=BytesIO(b'public fixture'),filename='test.txt'),db=object())
    if failure:
        with pytest.raises(HTTPException) as exc: asyncio.run(run())
        assert exc.value.status_code == (400 if failure=='value' else 502)
    else: assert asyncio.run(run())=={'id':1}


def test_principle_route_mutations_keep_errors_local(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException
    principal=object()
    class DB:
        def get(self,*args): return principal
    class Service:
        def decide_principle(self,*args,**kw): return principal
        def merge_principle(self,*args,**kw): return principal
        def revise_principle(self,*args,**kw): return principal
    monkeypatch.setattr(route,'KnowledgeLibraryService',Service)
    monkeypatch.setattr(route,'_principle',lambda p:{'id':1})
    assert route.action_principle(1,route.PrincipleAction(action='approve'),DB())=={'id':1}
    assert route.action_principle(1,route.PrincipleAction(action='merge',canonical_principle_id=2),DB())=={'id':1}
    assert route.revise_principle(1,route.PrincipleRevision(principle='public fixture'),DB())=={'id':1}
    with pytest.raises(HTTPException): route.action_principle(1,route.PrincipleAction(action='merge'),SimpleNamespace(get=lambda *args: None))
    monkeypatch.setattr(Service,'decide_principle',lambda *a,**k:(_ for _ in ()).throw(ValueError('synthetic')))
    with pytest.raises(HTTPException) as exc: route.action_principle(1,route.PrincipleAction(action='approve'),DB())
    assert exc.value.status_code==409


def test_principles_list_explicit_filters(monkeypatch):
    from types import SimpleNamespace
    sql=[]
    db=SimpleNamespace(scalars=lambda statement: sql.append(str(statement)) or SimpleNamespace(all=lambda: []))
    assert route.list_principles(status='proposed',collection_id=3,limit=4,db=db)==[]
    assert 'collection_id' in sql[0] and 'status' in sql[0]
