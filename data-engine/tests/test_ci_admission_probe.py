"""Disposable probe must measure safe fields, rejects, queue and cancellation."""
import asyncio
import json

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.core import db_admission as admission
from app.core.auth import get_research_principal
from scripts.ci_admission_probe import Recorder, install_probe, make_app
from scripts.summarize_admission_probe import summarize

CASE = 'aabbccddeeff0011'


def test_probe_refuses_non_test_or_disabled_env(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('E2E_ADMISSION_TRACE', '1')
    with pytest.raises(RuntimeError):
        make_app()
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.delenv('E2E_ADMISSION_TRACE')
    with pytest.raises(RuntimeError):
        make_app()


def test_jsonl_status_peaks_markers_and_no_credentials(monkeypatch, tmp_path):
    destination = tmp_path/'safe.jsonl'
    recorder = Recorder(destination)
    gate = admission.AdmissionGate(2, 1, wait_seconds=0.01)
    monkeypatch.setattr(admission, 'request_gate', lambda: gate)
    original_slot = admission.AdmissionGate.slot
    # Register restoration before install mutates the class.
    monkeypatch.setattr(admission.AdmissionGate, 'slot', original_slot)
    app = FastAPI()
    app.dependency_overrides[get_research_principal] = lambda: None
    entered, release = asyncio.Event(), asyncio.Event()
    @app.post('/api/read')
    async def read(slot=Depends(admission.admit_database_request)):
        entered.set()
        await release.wait()
        return {'ok': True}
    install_probe(app, recorder)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get(f'/_ci/admission-mark/start/{CASE}/0')).status_code == 204
            first = asyncio.create_task(client.post('/api/read?secret=QUERY', json={'password': 'BODY'},
                                                    headers={'Cookie': 'COOKIE', 'Authorization': 'SECRET'}))
            await entered.wait()
            assert (await client.post('/api/read')).status_code == 429
            release.set()
            assert (await first).status_code == 200
            assert (await client.get(f'/_ci/admission-mark/end/{CASE}/0')).status_code == 204
    asyncio.run(scenario())
    raw = destination.read_text()
    for secret in ['QUERY', 'BODY', 'COOKIE', 'SECRET', 'anonymous', 'Authorization', 'password']:
        assert secret not in raw
    events = [json.loads(line) for line in raw.splitlines()]
    ends = [e for e in events if e['event'] == 'end']
    assert {e['status'] for e in ends} == {200, 429}
    assert len({e['tenant'] for e in ends}) == 1
    assert len({e['request_id'] for e in ends}) == 2
    assert all(e['path'] == '/api/read' and e['method'] == 'POST' for e in ends)
    assert all(e['monotonic_end'] >= e['monotonic_start'] for e in ends)
    assert sum(e['admitted'] for e in ends) == 1
    report = summarize(events)
    case = report['cases'][0]
    assert case['total_started'] == 2 and case['2xx'] == case['429'] == 1
    assert case['503'] == 0
    assert case['peak_attempted'] == 2 and case['peak_admitted'] == 1
    assert case['inflight_initial']['attempted_global'] == case['inflight_final']['attempted_global'] == 0
    assert report['unclosed_requests'] == 0


def test_cancellation_is_499_and_releases_probe_attempts(monkeypatch, tmp_path):
    destination = tmp_path/'cancel.jsonl'
    recorder = Recorder(destination)
    gate = admission.AdmissionGate(2, 1)
    monkeypatch.setattr(admission, 'request_gate', lambda: gate)
    monkeypatch.setattr(admission.AdmissionGate, 'slot', admission.AdmissionGate.slot)
    app = FastAPI()
    app.dependency_overrides[get_research_principal] = lambda: None
    entered = asyncio.Event()
    @app.get('/read')
    async def read(slot=Depends(admission.admit_database_request)):
        entered.set()
        await asyncio.Event().wait()
    install_probe(app, recorder)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            request = asyncio.create_task(client.get('/read'))
            await entered.wait()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
    asyncio.run(scenario())
    last = json.loads(destination.read_text().splitlines()[-1])
    assert last['status'] == 499 and last['admitted'] is True
    assert last['inflight_final']['attempted_global'] == last['inflight_final']['admitted_global'] == 0


def test_summary_exposes_carry_and_unclosed_windows():
    counts = {'attempted_global': 1, 'admitted_global': 1, 'attempted_tenant': 1, 'admitted_tenant': 1}
    events = [
        {'event': 'attempt', 'request_id': 'old', 'tenant': 't', 'monotonic': 0.5, 'inflight': counts},
        {'event': 'marker', 'action': 'start', 'case_id': CASE, 'attempt': 0, 'monotonic': 1, 'inflight': counts},
        {'event': 'attempt', 'request_id': 'new', 'tenant': 't', 'method': 'GET', 'path': '/read', 'monotonic': 2, 'inflight': counts},
        {'event': 'marker', 'action': 'end', 'case_id': CASE, 'attempt': 0, 'monotonic': 3, 'inflight': counts},
        {'event': 'end', 'request_id': 'old', 'monotonic_start': 0.5, 'monotonic_end': 4, 'monotonic': 4},
    ]
    result = summarize(events)
    assert result['cases'][0]['carry_in_observed'] == result['cases'][0]['carry_out'] == 1
    assert result['unclosed_requests'] == 1
    assert summarize(events[:2])['unclosed_markers'] == [{'case_id': CASE, 'attempt': 0}]


def test_lifespan_plain_slot_exception_and_factory(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    import scripts.ci_admission_probe as probe
    app = FastAPI()
    gate = admission.AdmissionGate(2, 1)
    monkeypatch.setattr(admission, 'request_gate', lambda: gate)
    monkeypatch.setattr(admission.AdmissionGate, 'slot', admission.AdmissionGate.slot)
    @app.get('/error')
    async def error():
        async with gate.slot('private-tenant'):
            raise ValueError('local failure')
    recorder = Recorder(tmp_path/'errors.jsonl')
    install_probe(app, recorder)
    async def scenario():
        async with gate.slot('background-no-http'):
            assert gate.active == 1
        async with app.router.lifespan_context(app):
            pass
        messages = iter([{'type': 'lifespan.startup'}, {'type': 'lifespan.shutdown'}])
        async def receive():
            return next(messages)
        async def send(message):
            assert message['type'] in {'lifespan.startup.complete', 'lifespan.shutdown.complete'}
        await app({'type': 'lifespan'}, receive, send)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            with pytest.raises(ValueError):
                await client.get('/error')
    asyncio.run(scenario())
    end = json.loads(recorder.destination.read_text().splitlines()[-1])
    assert end['status'] == 500 and end['inflight_final']['attempted_global'] == 0
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('E2E_ADMISSION_TRACE', '1')
    monkeypatch.setitem(sys.modules, 'main', SimpleNamespace(app=app))
    monkeypatch.setattr(probe, 'install_probe', lambda candidate, recorder: None)
    assert make_app() is app


def test_summary_command_and_orphan_end(monkeypatch, tmp_path):
    import sys

    from scripts.summarize_admission_probe import main
    source, destination = tmp_path/'events.jsonl', tmp_path/'sub'/'summary.json'
    source.write_text(json.dumps({'event': 'marker', 'action': 'end', 'case_id': CASE,
                                 'attempt': 0, 'monotonic': 1, 'inflight': {}})+'\n\n')
    monkeypatch.setattr(sys, 'argv', ['summary', str(source), str(destination)])
    main()
    assert json.loads(destination.read_text())['cases'] == []
