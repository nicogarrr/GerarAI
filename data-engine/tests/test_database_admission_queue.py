"""Normal bursts queue without DB sessions; overload stays bounded."""
import asyncio

import pytest
from fastapi import HTTPException

from app.core.db_admission import AdmissionGate


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


def test_eight_request_normal_burst_queues_at_four_without_errors():
    async def scenario():
        gate = AdmissionGate(8, 4)
        entered = 0
        peak = 0
        release = asyncio.Event()
        async def request():
            nonlocal entered, peak
            async with gate.slot('a'):
                entered += 1
                peak = max(peak, gate.active)
                if entered <= 4:
                    await release.wait()
        tasks = [asyncio.create_task(request()) for _ in range(8)]
        await settle()
        assert gate.active == 4
        release.set()
        await asyncio.gather(*tasks)
        assert entered == 8 and peak <= 4
        assert gate.active == 0 and gate.tenants == {}
    asyncio.run(scenario())


def test_waiter_cancel_does_not_leak_queue_or_block_next():
    async def scenario():
        gate = AdmissionGate(2, 1)
        async with gate.slot('a'):
            async def waiting():
                async with gate.slot('a'):
                    pytest.fail('cancelled waiter entered')
            waiter = asyncio.create_task(waiting())
            await settle()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert gate.active == 1
        async with gate.slot('a'):
            assert gate.active == 1
        assert gate.pending == 0 and gate.tenants == {}
    asyncio.run(scenario())


def test_short_deadline_leaves_no_pending_tokens():
    async def scenario():
        gate = AdmissionGate(2, 1, wait_seconds=0.02)
        async with gate.slot('a'):
            with pytest.raises(HTTPException) as exc:
                async with gate.slot('a'):
                    pytest.fail('tenant cap bypassed')
            assert exc.value.status_code == 429
            assert exc.value.headers['Retry-After'] == '1'
            assert gate.pending == 0 and gate.active == 1
        assert gate.active == 0
    asyncio.run(scenario())


def test_saturated_tenant_does_not_block_other_tenant_and_fifo():
    async def scenario():
        gate = AdmissionGate(3, 2)
        order = []
        async with gate.slot('a'):
            async with gate.slot('a'):
                async def queued(name):
                    async with gate.slot('a'):
                        order.append(name)
                first = asyncio.create_task(queued('first'))
                await settle()
                second = asyncio.create_task(queued('second'))
                await settle()
                # Spare active slot is reserved for another tenant even with
                # A's waiters already ahead. They must not head-of-line block B.
                async with gate.slot('b'):
                    assert gate.active == 3
                    assert order == []
            await asyncio.gather(first, second)
        assert order == ['first', 'second']
        assert gate.pending == gate.active == 0
    asyncio.run(scenario())


def test_pending_budget_rejects_excess_without_opening_more_slots():
    async def scenario():
        gate = AdmissionGate(2, 1, max_pending=1, max_pending_per_tenant=1)
        entered = asyncio.Event()
        async def wait():
            async with gate.slot('a'):
                entered.set()
        async with gate.slot('a'):
            pending = asyncio.create_task(wait())
            await settle()
            with pytest.raises(HTTPException) as exc:
                async with gate.slot('a'):
                    pytest.fail('pending cap bypassed')
            assert exc.value.status_code == 429
            assert gate.active == 1 and gate.pending == 1
        await pending
        assert entered.is_set() and gate.pending == gate.active == 0
    asyncio.run(scenario())


def test_deadline_cannot_be_bypassed_when_capacity_returns_late(monkeypatch):
    import app.core.db_admission as admission
    clock = [0.0]
    monkeypatch.setattr(admission.time, 'monotonic', lambda: clock[0])
    async def scenario():
        gate = AdmissionGate(2, 1, wait_seconds=1)
        async def waiting():
            async with gate.slot('a'):
                pytest.fail('entered after deadline')
        async with gate.slot('a'):
            waiter = asyncio.create_task(waiting())
            await settle()
            clock[0] = 2.0
        with pytest.raises(HTTPException):
            await waiter
        assert gate.active == gate.pending == 0
    asyncio.run(scenario())


def test_fifo_among_eligible_tenants_after_global_capacity_returns():
    async def scenario():
        gate = AdmissionGate(2, 1)
        order = []
        async def waiting(tenant):
            async with gate.slot(tenant):
                order.append(tenant)
        async with gate.slot('holder-a'):
            async with gate.slot('holder-b'):
                first = asyncio.create_task(waiting('c'))
                await settle()
                second = asyncio.create_task(waiting('d'))
                await settle()
                assert gate.pending == 2 and gate.active == 2
            await asyncio.gather(first, second)
        assert order == ['c', 'd']
        assert gate.active == gate.pending == 0
    asyncio.run(scenario())


def test_queued_request_never_constructs_db_session_and_health_stays_free(monkeypatch):
    from types import SimpleNamespace

    import httpx
    from fastapi import Depends, FastAPI

    import app.core.database as coredb
    from app.core import db_admission as admission
    from app.core.auth import get_research_principal
    gate = AdmissionGate(2, 1)
    monkeypatch.setattr(admission, 'request_gate', lambda: gate)
    created = []
    class Session:
        def __init__(self):
            self.info = {}
            self.closed = False
        def rollback(self):
            pass
        def close(self):
            self.closed = True
    def factory():
        session = Session()
        created.append(session)
        return session
    monkeypatch.setattr(coredb, 'SessionLocal', factory)
    monkeypatch.setattr(coredb, 'settings', SimpleNamespace(research_auth_required=False, is_production=False))
    app = FastAPI()
    app.dependency_overrides[get_research_principal] = lambda: None
    entered, release = asyncio.Event(), asyncio.Event()
    @app.get('/read')
    async def read(db=Depends(coredb.get_db)):
        entered.set()
        await release.wait()
        return {'ok': True}
    @app.get('/health')
    async def health():
        return {'ok': True}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            first = asyncio.create_task(client.get('/read'))
            await entered.wait()
            waiting = asyncio.create_task(client.get('/read'))
            async with asyncio.timeout(1):
                while not gate.pending:
                    await asyncio.sleep(0.001)
            assert gate.pending == 1 and len(created) == 1
            assert (await client.get('/health')).status_code == 200
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert len(created) == 1 and gate.pending == 0
            release.set()
            assert (await first).status_code == 200
            assert (await client.get('/read')).status_code == 200
            assert len(created) == 2 and all(s.closed for s in created)
        assert gate.active == gate.pending == 0
    asyncio.run(scenario())


def test_zero_deadline_explicitly_preserves_fail_fast_mode():
    async def scenario():
        gate = AdmissionGate(2, 1, wait_seconds=0)
        async with gate.slot('a'):
            with pytest.raises(HTTPException) as exc:
                async with gate.slot('a'):
                    pytest.fail('tenant cap bypassed')
            assert exc.value.status_code == 429
            assert gate.pending == 0
    asyncio.run(scenario())


def test_global_pending_cap_applies_across_different_tenants():
    async def scenario():
        gate = AdmissionGate(1, 1, max_pending=1, max_pending_per_tenant=16)
        async def waiting():
            async with gate.slot('b'):
                pass
        async with gate.slot('a'):
            pending = asyncio.create_task(waiting())
            await settle()
            with pytest.raises(HTTPException) as exc:
                async with gate.slot('c'):
                    pytest.fail('global queue cap bypassed')
            assert exc.value.status_code == 503
            assert gate.pending == 1 and gate.active == 1
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        assert gate.pending == gate.active == 0
    asyncio.run(scenario())


def test_new_tenant_cannot_overtake_eligible_waiter_between_polls(monkeypatch):
    from types import SimpleNamespace

    from app.core import db_admission as admission

    async def scenario():
        gate = AdmissionGate(1, 1)
        order = []
        polls = asyncio.Queue()

        async def paused_poll(delay):
            resume = asyncio.Event()
            polls.put_nowait(resume)
            await resume.wait()

        # Replace only the gate's sleep, not asyncio's shared module. A waiter
        # remains parked until the test explicitly permits its next poll.
        monkeypatch.setattr(admission, 'asyncio', SimpleNamespace(sleep=paused_poll))

        async def request(tenant):
            async with gate.slot(tenant):
                order.append(tenant)

        tasks = []
        try:
            async with gate.slot('holder'):
                waiter = asyncio.create_task(request('older'))
                tasks.append(waiter)
                older_poll = await polls.get()
                assert gate.pending == gate.active == 1
            assert gate.active == 0 and gate.pending == 1
            newcomer = asyncio.create_task(request('new-tenant'))
            tasks.append(newcomer)
            # Run newcomer before allowing the eligible older waiter to poll.
            # Without the anti-overtaking condition it finishes immediately.
            await settle()
            assert order == [], 'new tenant overtook an already eligible waiter'
            assert gate.active == 0 and gate.pending == 2
            newer_poll = polls.get_nowait()
            older_poll.set()
            await waiter
            assert order == ['older']
            newer_poll.set()
            await newcomer
            assert order == ['older', 'new-tenant']
        finally:
            for task in tasks:
                task.cancel()  # harmless for a task already completed
            await asyncio.gather(*tasks, return_exceptions=True)
        assert gate.active == gate.pending == 0 and gate.tenants == {}

    asyncio.run(scenario())
