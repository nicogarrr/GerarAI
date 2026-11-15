"""Synthetic local ASGI bursts, NOT real desktop/mobile request measurements.

From data-engine: PYTHONPATH=.:tests python scripts/benchmark_database_admission_queue.py
"""
from __future__ import annotations

import ast
import asyncio
import json
import statistics
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import Depends, FastAPI, Header
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

import app.core.database as coredb
import tests.conftest  # noqa: F401 -- test environment before app imports
from app.core import db_admission as admission
from app.core.auth import get_research_principal
from app.models import Tenant
from app.models.entities import Base

BASE = '40235252679c8b3ef7978dafaf9a95814cb789b8'


async def measure(gate_type, engine):
    gate = gate_type(8, 4)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    async def identity(x_tenant: str = Header()):
        return SimpleNamespace(tenant_external_id=x_tenant, user_id='user', email=None)
    app.dependency_overrides[get_research_principal] = identity
    @app.get('/read')
    async def read(db=Depends(coredb.get_db)):
        db.execute(text('SELECT 1'))
        await asyncio.sleep(0.02)  # artificial DB-holding work, documented
        return {'ok': True}
    @app.get('/health')
    async def health():
        return {'ok': True}
    latencies = []
    statuses = Counter()
    peaks = []
    pool_peak = [0]
    def checkout(conn, record, proxy):
        pool_peak[0] = max(pool_peak[0], engine.pool.checkedout())
    event.listen(engine, 'checkout', checkout)
    try:
        with patch.object(admission, 'request_gate', return_value=gate), patch.object(coredb, 'SessionLocal', factory), patch.object(
            coredb, 'settings', SimpleNamespace(research_auth_required=True, is_production=False)
        ), patch('app.core.i18n.get_settings', return_value=SimpleNamespace(i18n_generation_enabled=False)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                async def request(tenant):
                    started = time.perf_counter()
                    response = await client.get('/read', headers={'x-tenant': tenant})
                    latencies.append((time.perf_counter()-started)*1000)
                    statuses[response.status_code] += 1
                for _ in range(20):
                    tasks = [asyncio.create_task(request(t)) for t in ['a']*8+['b']*2]
                    await asyncio.sleep(0.005)
                    peaks.append(gate.active)
                    assert (await client.get('/health')).status_code == 200
                    await asyncio.gather(*tasks)
                    assert gate.active == 0 and gate.tenants == {}
                    assert engine.pool.checkedout() == 0
    finally:
        event.remove(engine, 'checkout', checkout)
    return {'n_bursts': 20, 'requests': len(latencies), 'statuses': dict(statuses),
            'p50_ms': statistics.median(latencies), 'p95_ms': sorted(latencies)[189],
            'peak_active_observed': max(peaks), 'pool_peak_checked_out': pool_peak[0],
            'samples_ms': latencies}


def main():
    source = subprocess.check_output(['git', 'show', f'{BASE}:data-engine/app/core/db_admission.py'], text=True)
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'AdmissionGate')
    scope = dict(vars(admission))
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<base-admission-gate>', 'exec'), scope)
    with tempfile.TemporaryDirectory() as folder:
        engine = create_engine(f'sqlite:///{folder}/queue.db', poolclass=QueuePool, pool_size=10,
                               max_overflow=0, connect_args={'check_same_thread': False})
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            db.add_all([Tenant(external_id='a'), Tenant(external_id='b')])
            db.commit()
        report = {'baseline': BASE, 'workload': '20 ASGI bursts, each 8A+2B, artificial20ms hold, real get_db, SQLite QueuePool10/overflow0',
                  'network': False, 'real_frontend': False,
                  'before': asyncio.run(measure(scope['AdmissionGate'], engine)),
                  'after': asyncio.run(measure(admission.AdmissionGate, engine)),
                  'caveat': 'Synthetic backpressure verification only. Does not measure actual desktop/mobile peaks or PostgreSQL pool health.'}
        engine.dispose()
    destination = Path(__file__).resolve().parents[2] / 'docs/performance/evidence/database-admission-queue-2026-11-16.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2)+'\n')
    print({k: {a: b for a, b in v.items() if a != 'samples_ms'} if isinstance(v, dict) else v for k, v in report.items()})


if __name__ == '__main__':
    main()
