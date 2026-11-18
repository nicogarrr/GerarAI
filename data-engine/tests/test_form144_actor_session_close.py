import pytest

from app.services import form144_monitor as m
from app.workers import dramatiq_app as w


@pytest.mark.parametrize('failure',['lease','scan'])
def test_form144_closes_session_on_failure(monkeypatch,failure):
    seen=[]
    class DB:
        info={'tenant_id':7}
        def close(self):seen.append('closed')
    monkeypatch.setattr(w,'_session',lambda *a:DB())
    monkeypatch.setattr(w,'_lease_redis_url',lambda:None)
    monkeypatch.setattr(w,'_handle_actor_error',lambda *a,**k:{'status':'caught'})
    def boom(*a,**kw):raise RuntimeError('audit_failure')
    monkeypatch.setattr(w,'acquire_job_lease',boom if failure=='lease' else lambda *a,**k:object())
    monkeypatch.setattr(w,'release_job_lease',lambda *a,**k:seen.append('released'))
    monkeypatch.setattr(m,'scan',boom)
    assert w.scan_form144_watchlist.fn(tenant_id=7)=={'status':'caught'}
    assert seen.count('closed')==1
    assert ('released' in seen)==(failure=='scan')

def test_form144_closes_when_lease_held(monkeypatch):
    seen=[]
    class DB:
        info={'tenant_id':7}
        def close(self):seen.append('closed')
    monkeypatch.setattr(w,'_session',lambda *a:DB())
    monkeypatch.setattr(w,'_lease_redis_url',lambda:None)
    monkeypatch.setattr(w,'acquire_job_lease',lambda *a,**k:None)
    result=w.scan_form144_watchlist.fn(tenant_id=7)
    assert result['reason']=='lease_held'
    assert seen==['closed']
