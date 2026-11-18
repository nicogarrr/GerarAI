import threading
from datetime import date
from unittest.mock import Mock

import httpx
import pytest
from dramatiq.middleware import CurrentMessage
from sqlalchemy import select

from app.models.entities import Document
from app.services import finnhub_profile_backfill as m
from app.services.connectors import finnhub
from app.services.connectors.global_pacing import GlobalPacer
from app.workers import dramatiq_app as w

# `db` se importa a proposito: importar el fixture lo registra en este
# modulo (ruff F401 no puede saberlo). SimpleNamespace del archivo original
# del auditor no se usaba y se ha quitado.
from tests.test_finnhub_profile_backfill import (  # noqa: F401
    _Client,
    _Client429,
    _company,
    _FakePacer,
    _Settings,
    db,
)


def test_resume_after_close_next_day_without_repeating_documents(db):
    for i in range(4):
        _company(db, f'M{i}')
    class Partial:
        def __init__(self): self.calls=[]
        def get(self,url,params=None):
            self.calls.append(params['symbol'])
            if params['symbol']=='M2':
                return httpx.Response(429,headers={'Retry-After':'90'})
            return httpx.Response(200,json={'name':'Real company'})
        def close(self): pass
    first=Partial()
    result=m.FinnhubProfileBackfill(settings=_Settings(),client=first,pacer=_FakePacer()).backfill(db,today=date(2026,11,18))
    assert result['procesadas']==2
    assert len(db.scalars(select(Document)).all())==2
    db.close()
    client=_Client(profiles={f'M{i}':{'name':'Real company'} for i in range(4)})
    result=m.FinnhubProfileBackfill(settings=_Settings(),client=client,pacer=_FakePacer()).backfill(db,today=date(2026,11,19))
    assert result['procesadas']==2
    assert len(client.calls)==4
    assert len(db.scalars(select(Document)).all())==4


def test_rate_limit_published_even_if_db_commit_fails(db,monkeypatch):
    _company(db,'FAIL')
    pacer=_FakePacer()
    monkeypatch.setattr(db,'commit',Mock(side_effect=RuntimeError('commit unavailable')))
    with pytest.raises(RuntimeError,match='commit unavailable'):
        m.FinnhubProfileBackfill(settings=_Settings(),client=_Client429(90),pacer=pacer).backfill(db)
    assert pacer.cooldowns==[90]


def test_server_retry_after_not_shortened(db):
    _company(db,'LONG')
    pacer=_FakePacer()
    result=m.FinnhubProfileBackfill(settings=_Settings(),client=_Client429(172800),pacer=pacer).backfill(db)
    assert result['retry_after_seconds']==172800
    assert pacer.cooldowns==[172800]


def test_sync_sleep_does_not_block_another_lane_cooldown_probe():
    sleeping=threading.Event()
    release=threading.Event()
    probed=threading.Event()
    def sleeper(seconds):
        sleeping.set()
        release.wait(2)
    pacer=GlobalPacer('finnhub',min_interval_seconds=1.2,sleep=sleeper)
    pacer.wait_sync()
    waiter=threading.Thread(target=pacer.wait_sync)
    waiter.start()
    assert sleeping.wait(1)
    probe=threading.Thread(target=lambda:(pacer.blocked_for(),probed.set()))
    probe.start()
    try:
        assert probed.wait(.2),'another lane cannot inspect cooldown while sync backfill sleeps holding lock'
    finally:
        release.set()
        waiter.join(3)
        probe.join(3)


@pytest.mark.parametrize('retry',[0,1,2])
def test_real_message_retry_budget_does_not_dead_letter(retry,monkeypatch):
    monkeypatch.setattr(w,'_redis_client',lambda:None)
    monkeypatch.setattr(finnhub,'finnhub_blocked_for',lambda:45.)
    message=w.backfill_finnhub_profiles.message(tenant_id=1,user_id='u')
    message.options['retries']=retry
    token=CurrentMessage._MESSAGE.set(message)
    try:
        if retry<2:
            import dramatiq
            with pytest.raises(dramatiq.Retry):
                w.backfill_finnhub_profiles(tenant_id=1,user_id='u')
        else:
            assert w.backfill_finnhub_profiles(tenant_id=1,user_id='u')['reason']=='rate_limited_retries_exhausted'
    finally: CurrentMessage._MESSAGE.reset(token)
