from types import SimpleNamespace
from pathlib import Path
import pytest
from app.workers import dramatiq_app as app
from app.workers import scheduler as sched

class Redis:
    def __init__(self): self.values={}; self.closed=0
    def set(self,key,value,nx=False,ex=None):
        if nx and key in self.values:return False
        self.values[key]=value;return True
    def get(self,key):return self.values.get(key)
    def eval(self,script,n,key,token):
        if self.values.get(key)==token:self.values.pop(key)
    def close(self):self.closed+=1

class Db:
    def close(self):pass
    def rollback(self):pass

@pytest.fixture
def setup(monkeypatch):
    r=Redis();calls=[]
    monkeypatch.setattr(app,'_redis_client',lambda:r)
    monkeypatch.setattr(app,'_session',lambda *a:Db())
    monkeypatch.setattr(app,'_official_close_session_key',lambda:'2026-10-27')
    def sync(db):calls.append(1);return {'status':'ok','covered':2,'latest_date':'2026-10-27','target_date':'2026-10-27','target_coverage':1.0}
    monkeypatch.setattr('app.services.market_close_sync.sync_official_closes',sync)
    return r,calls

def test_dedicated_worker_and_one_scheduler_message(monkeypatch):
    assert app.sync_official_closes.queue_name=='official-closes'
    calls=[]
    monkeypatch.setattr(sched,'tenant_contexts',lambda:[(1,'a'),(2,'b')])
    monkeypatch.setattr(app.sync_official_closes,'send',lambda *a:calls.append(a) or SimpleNamespace(message_id='m'))
    sched.enqueue_official_closes_once();assert calls==[(1,'a')]
    compose=Path('../docker-compose.prod.yml').read_text()
    assert 'container_name: cavaai-worker-official-closes' in compose
    assert '"--threads", "1", "-Q", "official-closes"' in compose

def test_legacy_tenant_duplicates_skip_after_global_success(setup):
    r,calls=setup
    assert app.sync_official_closes.fn(1,'a')['status']=='ok'
    assert app.sync_official_closes.fn(2,'b')['reason']=='session_already_synced'
    assert calls==[1]
    assert 'cavaai:job-lease:sync_official_closes:global' not in r.values

def test_global_lease_blocks_other_tenant(setup):
    r,calls=setup;r.values['cavaai:job-lease:sync_official_closes:global']='other'
    assert app.sync_official_closes.fn(2,'b')['reason']=='lease_held'
    assert not calls

def test_partial_failure_does_not_mark_success(setup,monkeypatch):
    r,calls=setup
    monkeypatch.setattr('app.services.market_close_sync.sync_official_closes',lambda db:{'status':'partial','covered':1,'latest_date':'2026-10-27'})
    app.sync_official_closes.fn(1,'a')
    assert not any(':done:' in k for k in r.values)

def test_redis_failure_never_falls_back_to_process_lock(monkeypatch):
    monkeypatch.setattr(app,'_redis_client',lambda:None)
    with pytest.raises(RuntimeError,match='Redis required'):app.sync_official_closes.fn(1,'a')


def test_only_three_target_bars_cannot_mark_done(setup, monkeypatch):
    r,calls=setup
    monkeypatch.setattr('app.services.market_close_sync.sync_official_closes',lambda db:{'status':'ok','target_date':'2026-10-27','target_coverage':3/1952})
    app.sync_official_closes.fn(1,'a')
    assert not any(':done:' in k for k in r.values)

@pytest.mark.parametrize('result',[{'status':'partial','target_date':'2026-10-27','target_coverage':.95}, {'status':'ok','target_date':'2026-10-26','target_coverage':1.0}])
def test_partial_or_wrong_date_never_done(setup, monkeypatch,result):
    r,_=setup
    monkeypatch.setattr('app.services.market_close_sync.sync_official_closes',lambda db:result)
    app.sync_official_closes.fn(1,'a')
    assert not any(':done:' in k for k in r.values)

def test_holiday_full_download_attempts_capped_across_tenants(setup,monkeypatch):
    r,calls=setup
    def sync(db):
        calls.append(1)
        return {'status':'partial','target_date':'2026-10-27','target_coverage':0.0}
    monkeypatch.setattr('app.services.market_close_sync.sync_official_closes',sync)
    for i in range(3):app.sync_official_closes.fn(i,'a')
    assert app.sync_official_closes.fn(4,'b')['reason']=='session_attempt_cap'
    assert len(calls)==3

def test_existing_marker_requires_explicit_operator_cleanup(setup):
    r,calls=setup
    r.values['cavaai:official-closes:done:2026-10-27']='1'
    app.sync_official_closes.fn(1,'a')
    assert calls==[]
