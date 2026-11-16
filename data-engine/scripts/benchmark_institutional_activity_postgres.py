"""Explicitly local PG fixture harness. Uses/drops only a fresh private schema.

Requires disposable PostgreSQL on 127.0.0.1:6543, sandbox role, postgres DB.
APP_ENV=test PYTHONPATH=. python scripts/benchmark_institutional_activity_postgres.py
Never reads application connection settings or a remote database.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.models import Company
from app.models.entities import InstrumentReference
from app.models.public_market_data import PublicFinancialFact, PublicSourceDocument
from scripts.benchmark_institutional_activity import run


def main():
    schema = 'activity_bench_' + uuid.uuid4().hex
    engine = create_engine('postgresql+psycopg://sandbox@127.0.0.1:6543/postgres',
                           connect_args={'options': f'-csearch_path={schema}'})
    tables = [Company.__table__, InstrumentReference.__table__, PublicSourceDocument.__table__, PublicFinancialFact.__table__]
    with engine.begin() as conn:
        version = conn.scalar(select(func.version()))
        conn.execute(CreateSchema(schema))
    def factory():
        Company.metadata.drop_all(engine, tables=list(reversed(tables)))
        Company.metadata.create_all(engine, tables=tables)
        db = Session(engine)
        db.add(Company(ticker='AAPL', name='Synthetic', exchange='NASDAQ', company_type='mature',
                       valuation_model='dcf', isin='US0378331005'))
        db.commit()
        return db
    try:
        report = {'method': '7 sequential cold-ORM reads per scenario; tracemalloc overhead included; fixture setup excluded; NOT production',
                  'server_version': version, 'results': [run(n, factory=factory, engine_label='PostgreSQL local disposable') for n in (500, 2000)]}
        print(json.dumps(report, indent=2))
    finally:
        with engine.begin() as conn:
            conn.execute(DropSchema(schema, cascade=True))
        engine.dispose()


if __name__ == '__main__':
    main()
