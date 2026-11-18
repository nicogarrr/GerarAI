# Financial-facts counts: tenant/company index

## Scope and dependency

Revision `0138_facts_tenant_company_idx` (29 characters, fits Alembic's
VARCHAR(32)), down_revision `0137_form144_notices`. The initially requested
long name exceeded 32 characters; the short name was confirmed by Main.
The patch is stacked on UNMERGED Form144 v5b commit
`7a2e9be72c0f9a0caed38268f307781f6e61a389`. Merge only after that dependency
passes its own review. It is not a patch based on current main.

Adds general, nonunique B-tree `ix_facts_tenant_company_count` on
`financial_facts(tenant_id, company_id)`, aligned in ORM metadata.
No query, result, cache, tenant filtering or count semantics change.

## Production observations, not a production A/B

Pilot read-only evidence on 18 November 2026:

- 11:37-11:55 slow-query window: count facts grouped by company IN occurred
  8 times above the 1-second threshold, 11.3 seconds cumulative, max 1.92s.
  Three snapshot client responses were preceded around a second earlier
  by a 1.16-1.27s count. Temporal correlation, not request-ID attribution.
- Next snapshot logs: 9 calls, median 3065ms, p90 nearest rank 6362ms. No
  trace IDs, no controlled 20-load mobile experiment, all status 200.
- 12:15 index catalog: 9 indexes, no general tenant/company index. Separate
  tenant and company indexes and a partial health index do not cover the
  unqualified count. Approximate rows then 20.6M, heap 3.59GB and total
  including indexes/TOAST 6.73GB.
- 12:37 catalog estimate: 20,823,231 live and 964,080 dead tuples;
  relallvisible 432816/437827 pages = 98.86%; last autovacuum 05:32.
  This is catalog visibility, not pg_visibility. COUNT DISTINCT company
  was canceled at 15s. Current production company count and tenant
  distribution were not measured by that query.

### Backup distribution, separate from current production

Pilot's read-only measurement reported via Main at12:44 on18 November2026
comes from the09:54 backup snapshot, NOT current production:20,859,478
financial_facts rows,2,133 distinct companies and17 tenants. Tenant IDs were
not provided; positions below are descending row-count ranks, not IDs.

| Tenant rank | Rows | Distinct companies |
|---|---:|---:|
| 1 | 1,676,234 | 2,133 |
| 2 | 1,490,242 | 1,830 |
| 3 | 1,486,301 | 1,830 |
| 4 | 1,483,161 | 1,829 |
| 5 | 1,476,831 | 1,828 |
| 6 | 1,476,767 | 1,829 |
| 7 | 1,475,456 | 1,829 |
| 8 | 1,475,385 | 1,829 |
| 9 | 1,431,743 | 1,757 |
| 10 | 1,426,928 | 1,758 |
| Remaining7 combined | 5,960,430 | See company counts below |

Distinct-company counts for the remaining tenants, in the same descending
row-count ranking:11=1,758;12=1,758;13=1,758;14=1,757;15=826;16=34;17=2.
Individual row counts for ranks11-17 were not provided. Source evidence is
Pilot's backup aggregate, supplied via Main as
`facts-backup-aggregate-007b5967.json`: a sequential COPY aggregate of the
previously restored09:54 CET dump, not a query against live production.

The ten listed tenants total14,899,048 rows; adding the remaining7 matches
20,859,478. Each large tenant has about1.4-1.7M rows across about1,800-2,100
companies,786-815 rows/company (about800). Thus the tenant/company key is
selective relative to the complete facts table for a single company or a
small company set. This distribution supports the index choice; it is not
a planner/latency measurement, a guarantee for every company or IN-list, or
evidence that the synthetic80% tenant scenario matches real skew. Per-company
skew is not measured. These aggregate distinct-company counts
do not establish a within-tenant distribution of facts per company.

These observations select a target; they do not prove that this index will
remove the entire 2-6s snapshot time or establish a production improvement.

## Local PG 16.2 measurement

20M synthetic rows, 2000 companies, five tenant slots mapped to tenant1=80%
and tenant5=20%, 2000 rows per slot/company. Requested 40 companies of tenant1:
320,000 matched rows. Existing mapped indexes match the nine catalog indexes.
Synthetic source, metric mix, physical density and tenant/company skew are
not production replicas. Local heap 2.18GB, total before index 3.77GB.

One table, 30 samples per phase, fresh ORM sessions, warm/repeated-query
conditions. Order: baseline-clean, concurrent build, candidate-clean, update
320k target rows without vacuum, candidate-dirty, drop candidate,
baseline-dirty. This is sequential A/B, NOT alternating at 20M. The earlier
1M controls used 30 alternating pairs per condition. Exact results checked.

| State | Before median/p95 | With index median/p95 |
|---|---|---|
| all-visible clean pages | 100.19 / 115.53 ms | 19.46 / 20.14 ms |
| updated pages, no vacuum | 107.56 / 114.23 ms | 33.89 / 56.31 ms |

Separate EXPLAIN ANALYZE BUFFERS, not distribution samples:

- Clean: Index Scan company_id, 121.81ms/400453 shared hits, to Index Only
  Scan composite, 37.37ms/388 hits, zero heap fetches.
- Dirty: baseline 125.32ms/400479 hits plus4881 reads; candidate51.82ms,
  12821 hits and327820 heap fetches. Visibility matters materially.

Actual local CREATE INDEX CONCURRENTLY: 12.09s, index140,877,824B (134.35MiB)
clean; after updates143,147,008B. Straight row-count extrapolation to20.823M
is146.7MB (139.9MiB), NOT a capacity guarantee. Cardinality/dedup/bloat and
PG version change size. Allow headroom for index, temporary sort/WAL, and
other processes; do not use the final index size as required free disk.

The12s local build is NOT a production-duration estimate. Local machine,
I/O, cache, active transactions and write workload differ. Production build
and write latency must be observed by Pilot. No concurrent write throughput,
long-lived-reader waits, cold-cache HTTP latency or production CPU measured.

## Migration behavior and operations

PostgreSQL CREATE/DROP INDEX CONCURRENTLY inside Alembic autocommit_block,
not a regular transactional CREATE INDEX. Normal DML is permitted, but the
operation consumes I/O/CPU and takes locks/transaction waits: not zero impact.
The block commits preceding migration work. Do not wrap this revision in a
larger all-or-nothing transaction or claim its failure rolls earlier DDL back.

Reentry uses IF NOT EXISTS. A same-named INVALID index on financial_facts,
resolved through search_path, is dropped concurrently then recreated. The
catalog check is scoped by target table, not merely index name. PostgreSQL
resolves the target table OID through regclass and its exact namespace through
pg_class/pg_namespace. Repair DROP, CREATE and downgrade DROP all pass that
schema explicitly to Alembic, which quotes identifiers. Version3 only scoped
the catalog check: its unqualified repair DROP could delete an unrelated
same-named index earlier in search_path and leave the INVALID target intact.
Version4 fixes that demonstrated cross-schema bug. A valid
same-named index is retained; operator should verify its definition before
migration if there is possible schema drift. This patch does not delete
existing single-column or health indexes.

SQLite uses inspector guard and normal index DDL. Downgrade removes ONLY
this index, with IF EXISTS, and never deletes rows or tables. PostgreSQL
downgrade is also concurrent. Interrupted concurrent builds may leave an
INVALID index; reentry handles that state. Stop/cleanup/rollout belongs to
Pilot/Release, not this author. Monitor build progress, locks, disk, DB CPU,
read/write latency and errors; use the tested downgrade for index rollback.

## Tests

- Real PostgreSQL and SQLite upgrade/reentry/downgrade preserve all rows,
  column order tenant/company exact, nonunique index, repeated downgrade.
- PostgreSQL valid index OID unchanged on reentry.
- A real failed UNIQUE CONCURRENTLY build deliberately leaves INVALID;
  upgrade replaces it with the valid nonunique intended index, preserving
  duplicate company rows across tenants. No catalog tampering.
- Unit double verifies exact concurrent/autocommit flags and keys on invalid
  repair. It is not evidence of production lock timing.
- Two-schema PostgreSQL search_path collision regression: a valid foreign
  same-named index precedes the target table's schema. Both absent and INVALID
  target cases build the correct nonunique index, preserve the foreign index
  OID and rows, and downgrade only the target index. A mixed-case foreign
  schema with spaces also tests identifier quoting.
- Regression test fails against v3. Mutants removing schema from repair DROP,
  CREATE or downgrade DROP all fail the collision/exact-kwargs tests. The
  CREATE mutant is caught by exact kwargs, not by the collision test alone:
  an unqualified table name still resolves to the target in this fixture.
- Whole0138 file:31/31 lines and8/8 branches,100% separately. Operations plus
  chain tests16 passed,5 skips (three PostgreSQL-only cases on SQLite plus2
  existing CI-only chain checks). PostgreSQL cases were EXECUTED with explicit
  local URL on PG16.2. The independent Auditor's original repro was on PG14.
- Full actual Alembic PG chain: empty DB to0137, upgrade head0138, downgrade
  to0137, re-upgrade head. All4 commands passed on disposable database.
- Whole entities.py inherited branch suite:1812/1814 lines (99.89%),18/18
  branches (100%),16 passed. New index reflected from metadata.
- Ruff and git diff --check passed. Semgrep is not installed locally; no
  claim of a local Semgrep pass. No rules or suppressions changed.

Coverage commands from data-engine:

```sh
FACTS_INDEX_TEST_PG_URL=<disposable-local-PG> APP_ENV=test python -m pytest tests/test_0138_facts_tenant_company_idx.py tests/test_alembic_chain.py --cov=alembic/versions --cov-branch --cov-fail-under=0 --cov-report=json:/downloads/0138-coverage-all.json --cov-report=
python -m coverage report --include='*/0138_facts_tenant_company_idx.py' --fail-under=85
python -m coverage json --include='*/0138_facts_tenant_company_idx.py' -o /downloads/0138-coverage.json
APP_ENV=test python -m pytest tests/test_entities_whole_file_branches.py --cov=app.models.entities --cov-branch --cov-fail-under=85 --cov-report=json:/downloads/0138-entities-coverage.json
```

The include selects the entire migration, not changed lines. The first
coverage collection includes older migrations but the explicit85% gate is
applied to the complete new file; JSON records separate line/branch counts.
No coverage append or modification of thresholds in repository config.
