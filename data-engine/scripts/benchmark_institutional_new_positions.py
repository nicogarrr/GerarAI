"""Offline latency/query budget of the existing institutions read contract.

From data-engine: PYTHONPATH=.:tests python scripts/benchmark_institutional_new_positions.py
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from sqlalchemy import event

import tests.conftest  # noqa: F401 -- configure environment before app imports
from app.api.routes.ownership import institutional_holders_route
from app.models.public_market_data import PublicFinancialFact
from app.services import institutional_holders as service
from tests.test_institutional_holders import _db
from tests.test_institutional_new_positions import parsed_pair


def main():
    with _db() as db:
        service.ingest_parsed(db, parsed_pair(), ['new', 'prior'], service.universe_cusips(db))
        fact_count = db.query(PublicFinancialFact).count()
        queries = []
        def record(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)
        event.listen(db.bind, 'before_cursor_execute', record)
        samples = []
        previous = None
        try:
            for _ in range(50):
                db.expunge_all()
                queries.clear()
                started = time.perf_counter()
                output = institutional_holders_route('AAPL', db=db)
                samples.append((time.perf_counter()-started)*1000)
                assert len(queries) == 4
                if previous is not None:
                    assert output == previous
                previous = output
        finally:
            event.remove(db.bind, 'before_cursor_execute', record)
        report = {
            'fixture': 'SQLite memory, 15 current managers, 14 comparable new positions, 2 quarters, parsed SEC ZIP fixtures',
            'scope': 'existing route function, four local SELECTs, no HTTP transport/auth/production measurement',
            'n': len(samples), 'cold_first_ms': samples[0],
            'p50_ms': statistics.median(samples), 'p95_ms': sorted(samples)[47], 'samples_ms': samples,
            'queries': 4, 'stored_fact_rows': fact_count,
            'new_positions': output['new_positions'],
            'network': False, 'llm': False,
        }
    destination = Path(__file__).resolve().parents[2] / 'docs/performance/evidence/institutional-new-positions-2026-11-16.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2)+'\n')
    print({k: v for k, v in report.items() if k not in ('samples_ms', 'new_positions')})


if __name__ == '__main__':
    main()
