"""DISPOSABLE CI probe. Never merge or run on production.

Select via E2E_ADMISSION_TRACE=1 + APP_ENV=test and uvicorn scripts.ci_admission_probe:make_app --factory.
Only method/path (no query), random IDs, ephemeral tenant pseudonyms and numeric
counters/times/status are recorded. No request headers, cookies or bodies.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from app.core import db_admission

_MARK = re.compile(r'^/_ci/admission-mark/(start|end)/([a-f0-9]{16})/(\d+)$')
_REQUEST: ContextVar[dict | None] = ContextVar('ci_admission_request', default=None)


class Recorder:
    def __init__(self, destination: Path):
        self.destination = destination
        self._lock = threading.RLock()
        self._salt = os.urandom(32)
        self._attempted: dict[str, int] = {}
        self._current: dict = {}

    def pseudonym(self, tenant: str) -> str:
        return hashlib.blake2b(tenant.encode(), key=self._salt, digest_size=12).hexdigest()

    def _counts(self, gate, pseudonym=None, tenant=None):
        with gate._lock:
            return {'attempted_global': sum(self._attempted.values()),
                    'attempted_tenant': self._attempted.get(pseudonym, 0) if pseudonym else None,
                    'admitted_global': gate.active,
                    'admitted_tenant': gate.tenants.get(tenant, 0) if tenant else None,
                    'pending_global': len(gate._waiting)}

    def _write(self, event):
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        with self.destination.open('a', encoding='utf-8') as output:
            output.write(json.dumps(event, separators=(',', ':'))+'\n')

    def mark(self, action, case_id, attempt):
        gate = db_admission.request_gate()
        with self._lock:
            now = time.monotonic()
            event = {'event': 'marker', 'action': action, 'case_id': case_id,
                     'attempt': attempt, 'monotonic': now, 'inflight': self._counts(gate)}
            self._write(event)
            self._current = {'case_id': case_id, 'attempt': attempt} if action == 'start' else {}

    def begin(self, state, tenant, gate):
        with self._lock:
            pseudonym = self.pseudonym(tenant)
            self._attempted[pseudonym] = self._attempted.get(pseudonym, 0)+1
            state.update(tenant=pseudonym, monotonic_start=time.monotonic(), admitted=False,
                         **self._current)
            state['inflight_initial'] = self._counts(gate, pseudonym, tenant)
            self._write({**state, 'event': 'attempt', 'monotonic': state['monotonic_start'],
                         'inflight': state['inflight_initial']})

    def admitted(self, state, tenant, gate):
        with self._lock:
            state['admitted'] = True
            self._write({**state, 'event': 'admitted', 'monotonic': time.monotonic(),
                         'inflight': self._counts(gate, state['tenant'], tenant)})

    def end(self, state, tenant, gate):
        with self._lock:
            pseudonym = state['tenant']
            self._attempted[pseudonym] -= 1
            if not self._attempted[pseudonym]:
                del self._attempted[pseudonym]
            now = time.monotonic()
            self._write({**state, 'event': 'end', 'monotonic': now, 'monotonic_end': now,
                         'rejected': not state['admitted'],
                         'inflight_final': self._counts(gate, pseudonym, tenant),
                         'inflight': self._counts(gate, pseudonym, tenant)})


def install_probe(app, recorder):
    original_slot = db_admission.AdmissionGate.slot

    @asynccontextmanager
    async def observed_slot(gate, tenant):
        state = _REQUEST.get()
        if state is None:
            async with original_slot(gate, tenant):
                yield
            return
        recorder.begin(state, tenant, gate)
        state['_tenant'] = tenant
        state['_gate'] = gate
        try:
            async with original_slot(gate, tenant):
                recorder.admitted({k: v for k, v in state.items() if not k.startswith('_')}, tenant, gate)
                state['admitted'] = True
                yield
        finally:
            # The ASGI wrapper records final status only after response and
            # yield-dependency cleanup, including queued failures/cancellation.
            state['_slot_done'] = True

    db_admission.AdmissionGate.slot = observed_slot

    class ProbeMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http':
                return await self.app(scope, receive, send)
            marker = _MARK.fullmatch(scope['path'])
            if marker and scope['method'] == 'GET':
                recorder.mark(marker[1], marker[2], int(marker[3]))
                await send({'type': 'http.response.start', 'status': 204, 'headers': []})
                await send({'type': 'http.response.body', 'body': b''})
                return
            state = {'request_id': uuid.uuid4().hex, 'method': scope['method'], 'path': scope['path'], 'status': 499}
            token = _REQUEST.set(state)
            async def observed_send(message):
                if message['type'] == 'http.response.start':
                    state['status'] = message['status']
                await send(message)
            try:
                await self.app(scope, receive, observed_send)
            except asyncio.CancelledError:
                state['status'] = 499
                raise
            except BaseException:
                state['status'] = 500
                raise
            finally:
                if '_tenant' in state:
                    recorder.end({k: v for k, v in state.items() if not k.startswith('_')},
                                 state['_tenant'], state['_gate'])
                _REQUEST.reset(token)

    app.add_middleware(ProbeMiddleware)
    return original_slot


def make_app():
    if os.environ.get('APP_ENV') != 'test' or os.environ.get('E2E_ADMISSION_TRACE') != '1':
        raise RuntimeError('Disposable admission probe requires APP_ENV=test and E2E_ADMISSION_TRACE=1')
    import main
    destination = Path(os.environ.get('E2E_ADMISSION_TRACE_PATH', 'storage/admission-ci.jsonl'))
    install_probe(main.app, Recorder(destination))
    return main.app
