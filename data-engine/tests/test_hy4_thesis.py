import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.llm import hy4
from app.llm.contracts import LLMRequest, Message
from app.llm.errors import ProviderDisabledError
from app.llm.thesis_go import create_thesis_narrative_provider
from tests.test_hy4_guard import catalog, completion


@pytest.mark.parametrize('bad', [False, True])
def test_thesis_selected_hy4_is_go_guarded_without_http_scope(monkeypatch,bad):
    monkeypatch.setattr(hy4,'_blocked',False)
    calls=[]
    def handler(req):
        calls.append((req.method,str(req.url)))
        doc=completion()
        if bad: doc['usage']['cost']=1
        return httpx.Response(200,json=catalog() if req.method=='GET' else doc)
    cfg=Settings(app_env='test',thesis_go_model=hy4.MODEL,opencode_go_api_key='synthetic',
                 llm_free_only=True,thesis_go_api_key='unused-other-key')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider=create_thesis_narrative_provider(cfg,client=client)
            return await provider.complete(LLMRequest([Message('user','public synthetic narrative fixture')],task='thesis_deep_narrative'))
    if bad:
        with pytest.raises(ProviderDisabledError): asyncio.run(run())
        assert hy4.blocked()
    else: assert asyncio.run(run()).model==hy4.MODEL
    assert calls==[('GET',hy4.CATALOG),('POST',hy4.BASE+'/chat/completions')]
    assert not hy4._selected.get()
