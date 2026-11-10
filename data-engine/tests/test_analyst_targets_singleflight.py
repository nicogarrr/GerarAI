"""Yahoo concurrente: un lote por ticker sin compartir el deadline ni la prensa."""

import asyncio
import threading
import time

from app.services import analyst_targets_service as svc


def test_same_symbol_cold_requests_share_yahoo(monkeypatch):
    calls = []
    started = threading.Event()
    release = threading.Event()

    def fetch(symbol):
        calls.append(symbol)
        started.set()
        assert release.wait(2)
        return {"records": [], "consensus": {"mean": 90}, "currency": "USD"}

    monkeypatch.setattr(svc, "_fetch_sync", fetch)

    async def run():
        service = svc.AnalystTargetsService()
        first = asyncio.create_task(service.get("asts"))
        assert await asyncio.to_thread(started.wait, 1)
        second = asyncio.create_task(service.get(" ASTS "))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(first, second)
        assert all(r.status == "available" and r.consensus.mean == 90 for r in results)
        assert service._yahoo_inflight == {}
        assert (await service.get("ASTS")).status == "available"

    asyncio.run(run())
    assert calls == ["ASTS"]


def test_timeout_does_not_cancel_other_consumer_or_duplicate_thread(monkeypatch):
    calls = []
    started = threading.Event()
    release = threading.Event()

    def fetch(symbol):
        calls.append(symbol)
        started.set()
        assert release.wait(2)
        return {"records": [], "consensus": {"mean": 90}}

    monkeypatch.setattr(svc, "_fetch_sync", fetch)

    async def run():
        service = svc.AnalystTargetsService()
        short = asyncio.create_task(service.get("ASTS", deadline=time.monotonic() + 0.03))
        assert await asyncio.to_thread(started.wait, 1)
        assert (await short).note_code == "fetch_failed"
        assert (asyncio.get_running_loop(), "ASTS") in service._yahoo_inflight
        long = asyncio.create_task(service.get("ASTS", deadline=time.monotonic() + 1))
        await asyncio.sleep(0)
        release.set()
        assert (await long).status == "available"
        assert service._yahoo_inflight == {}

    asyncio.run(run())
    assert calls == ["ASTS"]


def test_cancelled_consumer_does_not_cancel_shared_fetch(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def fetch(symbol):
        started.set()
        assert release.wait(2)
        return {"records": [], "consensus": {"mean": 90}}

    monkeypatch.setattr(svc, "_fetch_sync", fetch)

    async def run():
        service = svc.AnalystTargetsService()
        first = asyncio.create_task(service.get("ASTS"))
        assert await asyncio.to_thread(started.wait, 1)
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass
        assert not service._yahoo_inflight[(asyncio.get_running_loop(), "ASTS")].cancelled()
        second = asyncio.create_task(service.get("ASTS"))
        await asyncio.sleep(0)
        release.set()
        assert (await second).status == "available"

    asyncio.run(run())


def test_different_symbols_not_serialized_and_failure_can_retry(monkeypatch):
    calls = []
    both = threading.Barrier(2)

    def fetch(symbol):
        calls.append(symbol)
        both.wait(timeout=2)
        if symbol == "BAD":
            raise ValueError("Yahoo unavailable")
        return {"records": [], "consensus": {"mean": 90}}

    monkeypatch.setattr(svc, "_fetch_sync", fetch)

    async def run():
        service = svc.AnalystTargetsService()
        good, bad = await asyncio.gather(service.get("ASTS"), service.get("BAD"))
        assert good.status == "available" and bad.note_code == "fetch_failed"
        assert service._yahoo_inflight == {}
        monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: {"records": [], "consensus": {}})
        assert (await service.get("BAD")).status == "empty"
        assert await service._yahoo("EXPIRED", -1) is None

    asyncio.run(run())
    assert sorted(calls) == ["ASTS", "BAD"]


def test_press_and_list_share_yahoo_but_keep_press_separate(monkeypatch):
    from app.services import analyst_targets_press as press

    started = threading.Event()
    release = threading.Event()
    calls = []
    press_calls = []

    def fetch(symbol):
        calls.append(symbol)
        started.set()
        assert release.wait(2)
        return {"records": [], "consensus": {"mean": 90}, "currency": "USD"}

    async def fake_press(symbol, **kwargs):
        press_calls.append(symbol)
        return []

    monkeypatch.setattr(svc, "_fetch_sync", fetch)
    monkeypatch.setattr(press, "fetch_press_targets", fake_press)

    async def run():
        service = svc.AnalystTargetsService()
        listing = asyncio.create_task(service.get("ASTS"))
        assert await asyncio.to_thread(started.wait, 1)
        detail = asyncio.create_task(service.get("ASTS", press=True))
        await asyncio.sleep(0.01)
        release.set()
        results = await asyncio.gather(listing, detail)
        assert all(r.status == "available" for r in results)
        assert set(service._cache) == {"ASTS", "ASTS|press"}
        assert service._yahoo_inflight == {}

    asyncio.run(run())
    assert calls == ["ASTS"] and press_calls == ["ASTS"]



def test_same_service_simultaneous_event_loops_never_share_tasks(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    service = svc.AnalystTargetsService()
    both_fetching = threading.Barrier(2)
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        # Ambos loops deben tener su propio Task y llegar a Yahoo. En la
        # versión anterior uno esperaba el Task del otro loop, fallaba y el
        # segundo fetch no llegaba a esta barrera.
        both_fetching.wait(timeout=2)
        return {"records": [], "consensus": {"mean": 90}}

    monkeypatch.setattr(svc, "_fetch_sync", fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(asyncio.run, service.get("ASTS")) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    assert all(result.status == "available" for result in results)
    assert calls == ["ASTS", "ASTS"]
    assert service._yahoo_inflight == {}
