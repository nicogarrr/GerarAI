"""Synthetic SELECT-only reader benchmark. Never connect to production.

Default SQLite is NOT a PostgreSQL benchmark. A real PostgreSQL run requires
an explicitly disposable empty database and is intentionally a separate task.
"""
from __future__ import annotations

import json
import statistics
import time
import tracemalloc
from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.services import institutional_holders as ih
from app.services.connectors.form13f_dataset import ManagerPeriod
from app.services.institutional_activity import institutional_activity
from tests.test_institutional_holders import APPLE, _db


def run(n: int, *, factory=_db, engine_label: str = "SQLite in-memory, synthetic, NOT PostgreSQL") -> dict:
    now, prior = date(2026, 6, 30), date(2026, 3, 31)
    current = {str(i).zfill(10): ManagerPeriod(str(i).zfill(10), f'Synthetic {i}', f'C{i}', date(2026, 8, 15),
               {APPLE: Decimal(i+10)}, values_usd={APPLE: Decimal(i*100)}) for i in range(1, n+1)}
    previous = {cik: ManagerPeriod(cik, m.manager, f'P{cik}', date(2026, 5, 15), {APPLE: Decimal(10)}) for cik, m in current.items()}
    with factory() as db:
        summary = ih.summarize({now: current, prior: previous}, APPLE, now, prior)
        ih.persist(db, db.query(ih.Company).filter_by(ticker='AAPL').one(), summary, cusip=APPLE,
                   dataset_url='https://www.sec.gov/synthetic', prior_url='https://www.sec.gov/synthetic-prior', checksum='bench')
        db.commit()
        counts = []
        scenarios = []
        fact_rows = db.query(ih.PublicFinancialFact).count()
        for status, page in (("all", 1), ("all", max(1, n//25)), ("reduce", 1)):
            samples = []
            peak = 0
            for _ in range(7):
                db.expunge_all()
                statements = []
                def record(conn, cursor, statement, parameters, context, executemany):
                    statements.append(statement)
                event.listen(db.bind, 'before_cursor_execute', record)
                tracemalloc.start()
                start = time.perf_counter()
                try:
                    result = institutional_activity(db, 'AAPL', status=status, page=page)
                finally:
                    event.remove(db.bind, 'before_cursor_execute', record)
                samples.append(round((time.perf_counter()-start)*1000, 3))
                peak = max(peak, tracemalloc.get_traced_memory()[1]); tracemalloc.stop()
                counts.append(len(statements))
                assert result['total'] == (n if status == 'all' else 0)
                assert len(result['rows']) == (25 if status == 'all' else 0)
                assert all(s.lstrip().upper().startswith('SELECT') for s in statements)
            scenarios.append({'status': status, 'page': page, 'read_ms': samples, 'p50_ms': statistics.median(samples), 'p95_ms': sorted(samples)[-1], 'peak_python_bytes': peak, 'response_bytes': len(json.dumps(result).encode())})
        return {'managers': n, 'engine': engine_label, 'scenarios': scenarios,
                'select_counts': counts, 'stored_fact_rows': fact_rows, 'page_size': 25,
                'measurement_note': 'Fresh ORM identity map per read. tracemalloc enabled, not comparable to uninstrumented earlier samples. All stored facts read on each page. No HTTP/auth.'}



if __name__ == '__main__':
    print(json.dumps({'method': '7 sequential cold-ORM reads per scenario; tracemalloc overhead included; fixture setup excluded',
                      'postgres_status': 'not_measured', 'results': [run(500), run(2000)]}, indent=2))
