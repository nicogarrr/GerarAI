import json
import statistics
import time
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import insert

from app.models import FinancialFact, MarketPrice
from app.services import propicks_gems_service as new
from tests.test_propicks_funnel import _company, _db
from tests.test_propicks_gems_eligible_work import result

unscoped = new._latest_fcf_and_shares

def baseline(db, candidates, today):
    new._latest_fcf_and_shares = lambda db, cutoff, **kwargs: unscoped(db, cutoff)
    try:
        return new.find_gems(db, candidates, today=today)
    finally:
        new._latest_fcf_and_shares = unscoped

with _db() as db:
 companies=[_company(f'B{i}') for i in range(500)];db.add_all(companies);db.flush()
 rows=[]
 for c in companies:
  for metric in ['free_cash_flow','shares_diluted']:
   for year in range(2023,2027):
    for rev in range(10):
     rows.append(dict(company_id=c.id,tenant_id=db.info['tenant_id'],metric=metric,value=Decimal('150000000') if metric=='free_cash_flow' else Decimal('100000000'),fiscal_year=year,fiscal_quarter='FY',period=f'FY{year}',unit='USD',source_type='test',created_at=datetime(2026,1,1,tzinfo=UTC)+timedelta(seconds=rev)))
 db.execute(insert(FinancialFact),rows)
 db.add(MarketPrice(company_id=companies[0].id,date=date(2026,11,16),close=Decimal('10')));db.commit()
 candidate=[result(companies[0])];reports=[]
 assert [asdict(x) for x in baseline(db,candidate,today=date(2026,11,16))]==[asdict(x) for x in new.find_gems(db,candidate,today=date(2026,11,16))]
 for name, function in [("unscoped-facts", baseline), ("scoped-facts", new.find_gems)]:
  samples=[]
  for _ in range(20):
   start=time.perf_counter();function(db,candidate,today=date(2026,11,16));samples.append((time.perf_counter()-start)*1000)
  reports.append(dict(variant=name,p50_ms=statistics.median(samples),p95_ms=sorted(samples)[18],samples_ms=samples))
 output={'fixture':'SQLite warm session;500companies,40000factrows,10revisions/year/metric;1candidate with fresh price;N20each;exact outputs equal','results':reports}
 Path('joyas-eligible-benchmark.json').write_text(json.dumps(output,indent=2));print(json.dumps(output,indent=2))
