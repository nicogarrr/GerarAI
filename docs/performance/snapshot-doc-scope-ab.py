import json,time,statistics,hashlib,importlib.util
from sqlalchemy import text,select
from app.core.database import SessionLocal
from app.models import Company
from app.services.company_snapshot_service import CompanySnapshotService as Baseline
spec=importlib.util.spec_from_file_location('candidate_snapshot','/tmp/candidate_snapshot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);Candidate=m.CompanySnapshotService
for batch in [1,10,40]:
 with SessionLocal() as db:
  db.info['tenant_id']=2;db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'));db.execute(text('SET statement_timeout=15000'))
  companies=list(db.scalars(select(Company).order_by(Company.id).limit(batch)).all()); times={'A':[],'B':[]};expected=None
  for r in range(8):
   for label,klass in ([('A',Baseline),('B',Candidate)] if r%2==0 else [('B',Candidate),('A',Baseline)]):
    db.expire_all();t=time.perf_counter();result=klass().build_many(db,companies);elapsed=round((time.perf_counter()-t)*1000,3)
    digest=hashlib.sha256(json.dumps({cid:o.model_dump(mode='json') for cid,o in result.items()},sort_keys=True).encode()).hexdigest()
    if expected is None:expected=digest
    assert digest==expected,(batch,r,label,digest,expected)
    if r>0:times[label].append(elapsed)
    print(json.dumps({'batch':batch,'round':r,'label':label,'ms':elapsed,'sha256':digest}),flush=True)
  print(json.dumps({'batch':batch,'medians':{k:statistics.median(v) for k,v in times.items()}}),flush=True)
