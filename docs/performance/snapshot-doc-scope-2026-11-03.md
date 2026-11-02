# Snapshot document ranking scope, 2026-11-03

Candidate base: b1aad286c. Production comparison code: main-351bc958.

CompanySnapshotService.build_many requests up to 40 companies. Its document
count ranked every immutable SEC archive document for the tenant before
filtering to the requested companies. Push the company partition-key filter
inside the window and keep it on the outer statement. The archive winner
still uses tenant/company/URL, publication date DESC NULLS LAST, id DESC.
No cache, schema/index, count approximation, or data mutation.

Read-only production DB session, tenant 2, REPEATABLE READ, statement timeout
15 seconds. Same process, alternating AB/BA, eight rounds, first pair excluded
from medians. db.expire_all before each call. JSON SHA256 identical for every
pair. Two independent runs; first 1/10/40 companies by company id. Not a
browser, endpoint, or cold-cache measurement. Backup pg_dump and COPY remained
SIGSTOP; ordinary workers including spotDL untouched. No claim of zero
background activity.

|Batch|Run1 baseline/candidate ms|Run2 baseline/candidate ms|
|---|---:|---:|
|1|101.154 / 86.763|91.011 / 68.805|
|10|209.112 / 114.938|178.259 / 109.312|
|40|196.769 / 188.337|175.323 / 156.135|

Raw rounds: snapshot-doc-scope-run1.jsonl and snapshot-doc-scope-run2.jsonl.
Harness: snapshot-doc-scope-ab.py. Place the baseline service on its normal
import path, candidate service at /tmp/candidate_snapshot.py and candidate
visibility helper at /tmp/candidate_visibility.py; candidate import changes
only to that helper for side-by-side isolation. No production module was
replaced. The final helper also filters the outer statement so callers cannot
accidentally expose unranked rows outside the supplied scope. The measured
callers already applied exactly that outer filter.

A different candidate narrowing latest-version window projection was rejected:
batch40 median 274.403 ms baseline versus 388.464 ms candidate. Not included.

Tests cover empty/single/multiple company scopes; winner, live URL and NULL URL
equivalence; publication/ID tie rules; tenant partition; SQL predicate inside
and outside ranking; existing snapshot batch/health/holding/endpoint cases.
