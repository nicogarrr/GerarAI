import tests.conftest
import json,math,subprocess,time
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
from sqlalchemy import create_engine,event
from sqlalchemy.orm import Session
from app.core.database import Base
from app.models import Portfolio,PortfolioDailySnapshot
from app.services.portfolio_quality_service import portfolio_quality
old={'__name__':'quality_reference'}
exec(compile(subprocess.check_output(['git','show','b1267e8f0:data-engine/app/services/portfolio_quality_service.py'],text=True),'reference.py','exec'),old)
engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
samples={'before':[],'after':[]};counts={};results={}
with Session(engine) as db:
 p=Portfolio(name='quality-ab',base_currency='EUR',is_default=True);db.add(p);db.flush()
 for i in range(3650):
  db.add(PortfolioDailySnapshot(portfolio_id=p.id,snapshot_date=date(2016,1,1)+timedelta(days=i),base_currency='EUR',positions_value_base=1000,cash_value_base=0,total_value_base=1000,pricing_coverage=Decimal('1'),daily_return=None if i==0 else Decimal('.01'),cumulative_twr=None if i==0 else Decimal('.01'),metadata_={'unused_blob':'x'*1000}))
 db.commit()
 for repeat in range(20):
  for name in (['before','after'] if repeat%2==0 else ['after','before']):
   db.expunge_all();queries=[];loads=[]
   def onquery(_conn,_cursor,sql,*args):queries.append(sql)
   def onload(_session,row):
    if isinstance(row,PortfolioDailySnapshot):loads.append(row)
   event.listen(engine,'before_cursor_execute',onquery);event.listen(db,'loaded_as_persistent',onload)
   t=time.perf_counter();result=old['portfolio_quality'](db) if name=='before' else portfolio_quality(db);samples[name].append((time.perf_counter()-t)*1000)
   event.remove(engine,'before_cursor_execute',onquery);event.remove(db,'loaded_as_persistent',onload)
   results[name]=result;counts[name]={'queries':len(queries),'snapshot_orm_loaded':len(loads)}
 assert results['before']==results['after']
out={'environment':'artificial local SQLite service, no HTTP/auth/providers/LLM/production','baseline':'b1267e8f0','snapshots':3650,'unused_metadata_bytes_per_row':1000,'results':{}}
for k,v in samples.items():out['results'][k]={'n':len(v),'p50_ms':sorted(v)[math.ceil(len(v)*.5)-1],'p95_ms':sorted(v)[math.ceil(len(v)*.95)-1],'samples_ms':v,**counts[k]}
Path('/tmp/quality-ab.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
