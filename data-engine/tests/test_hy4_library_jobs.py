import asyncio

import pytest

from app.llm.errors import ProviderDisabledError, ProviderHTTPError
from app.services import knowledge_library_service as kls
from app.services.budget import BudgetController
from tests.test_knowledge_library_bordes import CONTENIDO, _chunk, _documento, _Provider, db_tenant  # noqa: F401


def setup_doc(db_tenant, monkeypatch, batches=1):
    db, tid = db_tenant
    doc = _documento(db, tid)
    chunk = _chunk(db, doc, tid, CONTENIDO)
    provider = _Provider({'principles': []}); provider.name = 'hy4-go-zero'
    service = kls.KnowledgeLibraryService(provider)
    monkeypatch.setattr(service, '_principle_batches', lambda chunks: [[chunk]]*batches)
    return db, doc, provider, service


def test_zero_budget_three_calls_and_completed_marker(db_tenant, monkeypatch):
    db, doc, provider, service = setup_doc(db_tenant, monkeypatch, 3)
    costs=[]
    monkeypatch.setattr(BudgetController, 'can_spend', lambda self, db, amount: amount == 0)
    monkeypatch.setattr(BudgetController, 'record', lambda self, db, model, workflow, cost, *a, **kw: costs.append(cost))
    result=asyncio.run(service.extract_principle_batches(db,doc))
    assert len(provider.requests)==3 and result['batches_processed']==3
    assert costs==[0,0,0] and doc.metadata_['hy4_principle_run_state']=='completed'


def test_large_document_rejected_before_any_call(db_tenant,monkeypatch):
    db,doc,provider,service=setup_doc(db_tenant,monkeypatch,4)
    with pytest.raises(ProviderDisabledError,match='split'): asyncio.run(service.extract_principle_batches(db,doc))
    assert not provider.requests


@pytest.mark.parametrize('state',['in_progress','blocked'])
def test_interrupted_or_stopped_run_never_repeats(db_tenant,monkeypatch,state):
    db,doc,provider,service=setup_doc(db_tenant,monkeypatch)
    doc.metadata_={'hy4_principle_run_state':state};db.commit()
    with pytest.raises(ProviderDisabledError,match='review'): asyncio.run(service.extract_principle_batches(db,doc))
    assert not provider.requests


@pytest.mark.parametrize('status',[402,429,500])
def test_provider_failure_no_second_batch_or_actor_retry(db_tenant,monkeypatch,status):
    db,doc,provider,service=setup_doc(db_tenant,monkeypatch,3)
    calls=[]
    async def fail(request):calls.append(request);raise ProviderHTTPError('hy4',status)
    monkeypatch.setattr(provider,'complete',fail)
    with pytest.raises(ProviderDisabledError,match='no automatic'):asyncio.run(service.extract_principle_batches(db,doc))
    assert len(calls)==1 and doc.metadata_['hy4_principle_run_state']=='blocked'
    with pytest.raises(ProviderDisabledError):asyncio.run(service.extract_principle_batches(db,doc))
    assert len(calls)==1


def test_worker_interrupt_marker_blocks_broker_redelivery(db_tenant,monkeypatch):
    from dramatiq.middleware.time_limit import TimeLimitExceeded
    db,doc,provider,service=setup_doc(db_tenant,monkeypatch,3)
    calls=[]
    async def interrupted(request):calls.append(request);raise TimeLimitExceeded()
    monkeypatch.setattr(provider,'complete',interrupted)
    with pytest.raises(TimeLimitExceeded):asyncio.run(service.extract_principle_batches(db,doc))
    db.expire(doc)
    assert doc.metadata_['hy4_principle_run_state']=='in_progress'
    with pytest.raises(ProviderDisabledError):asyncio.run(service.extract_principle_batches(db,doc))
    assert len(calls)==1


def test_non_hy4_provider_failure_retains_existing_retry_class(db_tenant,monkeypatch):
    db,doc,provider,service=setup_doc(db_tenant,monkeypatch)
    provider.name='other'
    async def fail(request):raise ProviderHTTPError('other',429)
    monkeypatch.setattr(provider,'complete',fail)
    with pytest.raises(ProviderHTTPError):asyncio.run(service.extract_principle_batches(db,doc))
    assert not doc.metadata_


def test_atomic_admission_rejects_stale_document_view(db_tenant,monkeypatch):
    from sqlalchemy import update

    from app.models import KnowledgeDocument
    db,doc,provider,service=setup_doc(db_tenant,monkeypatch)
    execute=db.execute
    raced=False
    def race(statement,*args,**kwargs):
        nonlocal raced
        if getattr(statement,'is_update',False) and not raced:
            raced=True
            execute(update(KnowledgeDocument).where(KnowledgeDocument.id==doc.id).values(metadata_={'hy4_principle_run_state':'in_progress'}).execution_options(synchronize_session=False))
        return execute(statement,*args,**kwargs)
    monkeypatch.setattr(db,'execute',race)
    with pytest.raises(ProviderDisabledError,match='duplicate'):asyncio.run(service.extract_principle_batches(db,doc))
    assert not provider.requests
