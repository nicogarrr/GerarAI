import tests.conftest
import importlib.util,json,math,subprocess,time
from collections import Counter
from pathlib import Path
from sqlalchemy import create_engine,event
from sqlalchemy.orm import Session
from app.core.database import Base
from app.api.routes.companies import decision_journal,resolve_company
from app.services.fundamental_review_service import DecisionJournalService
from tests.test_journal_payload_work_budget import _fixture

old={"__name__":"journal_reference"}
exec(compile(subprocess.check_output(['git','show','b1267e8f0:data-engine/app/services/journal_trade_link.py'],text=True),'reference.py','exec'),old)
engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
samples={'before':[],'after':[]}; counts={}; results={}
with Session(engine) as db:
 _fixture(db,20)
 def before():
  company=resolve_company(db,'UBER')
  return [old['journal_entry_payload'](db,e) for e in DecisionJournalService().list(db,company)]
 for repeat in range(20):
  for name in (['before','after'] if repeat%2==0 else ['after','before']):
   db.expunge_all();queries=[];loads=Counter()
   def onquery(_conn,_cursor,sql,*args):queries.append(sql)
   def onload(_session,row):loads[type(row).__name__]+=1
   event.listen(engine,'before_cursor_execute',onquery);event.listen(db,'loaded_as_persistent',onload)
   t=time.perf_counter();result=before() if name=='before' else decision_journal('UBER',db);samples[name].append((time.perf_counter()-t)*1000)
   event.remove(engine,'before_cursor_execute',onquery);event.remove(db,'loaded_as_persistent',onload)
   results[name]=result;counts[name]={'queries':len(queries),'orm_loaded':dict(loads)}
 assert results['before']==results['after']
out={'environment':'artificial local SQLite direct route, no HTTP/auth/network/LLM/production','n_entries':20,'history_models':4,'history_theses':1,'results':{}}
for k,v in samples.items():out['results'][k]={'n':len(v),'p50_ms':sorted(v)[math.ceil(len(v)*.5)-1],'p95_ms':sorted(v)[math.ceil(len(v)*.95)-1],'samples_ms':v,**counts[k]}
Path('/tmp/journal-ab.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
