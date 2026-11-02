# Production cold endpoint investigation, 2026-11-02

Before, fc6478e8, tenant 2, uncached service path in a separate process using the deployed source. Backup concurrent, so not A/B evidence:

- data-health 41,825 ms: facts aggregation 26,491 ms, news 9,709 ms, prices 3,184 ms, documents 1,488 ms.
- metric-coverage 8,612 ms: calculated metric DISTINCT 4,271 ms, valuation outputs query 1,094 ms, distinct financial fact metrics 186 ms. SQL query timers exclude Python row hydration.
- All 0122 indexes are present, valid and ready. Facts plan uses a parallel sequential scan, sort and count distinct over a ~8.85M-row table. Calculated metric distinct uses ix_calc_metrics_tenant_metric_ok but traverses matching rows.
- Candidate calculated metric recursive distinct: EXPLAIN ANALYZE 86 ms, 26 metrics, existing partial index. This is not the old source/company recursive health query, which regressed in prior production evidence.
- Cold data-health is currently not consumed by frontend inventory UI, which was removed. Metric coverage blocks the screeners suggestions section.

Pending: repeated same-method A/B without concurrent backup, exact output equality, no false claim that measured backup load explains all of the cold cost. Do not deploy candidate files into /app for a benchmark.

Additional measured probes during backup (not A/B evidence):

- A predicate containing only company_id IS NOT NULL does not select the valid facts partial index, even when asking for the first ordered pair. A full INTEGER lower bound (>= -2147483648), which retains all possible stored IDs, selects ix_facts_health_src_cid as an Index Only Scan. Negative/zero/minimum IDs are covered by tests.
- Two-level bounded source/company count: 616.708 ms. Full candidate health inventory: 4,124.548 ms, no error sources (facts 334.567 ms, documents 656.284 ms, news 676.095 ms, prices 1,992.686 ms).
- Metric candidate standalone during backup: 4,097.427 ms, 87 names. Calculated metric recursive probes 41.191 ms. Output JSON extraction 3,420.357 ms; do not assume that projection is faster until the same-method A/B proves it.
- Existing partial index stats: valid/ready/live all true. Source schema is public, PostgreSQL 17.11 aarch64. No memory, planner or global database configuration changed.

Validation: Python 3.12 targeted combined suite 89 pass, one environment skip; all 2722 repository guards pass with the repository's module-mock flag. Initial guard invocation omitted that flag and used a node_modules symlink, causing two environment failures; rerun after fixing both passed. Ruff and diff whitespace checks pass. No guard relaxed.

Prices remain on the previous group-by path: the source/company probes are not assumed faster for its shape. Only tenant-owned facts/documents/news use the bounded candidate. New A/B must compare this final candidate.

## Final production-volume A/B without backup

The postdeploy backup and isolated restores finished before this measurement.
Baseline is deployed fc6478e8eb0a7dedbce9f6cac61e176403a11480, candidate modules
loaded from /tmp only, never replacing the deployed /app. Six rounds per service
in ABBAAB order, same Session, read-only repeatable-read transaction, tenant 2,
and fixed `now`. SQL timers exclude hydration; total service times include it.

| Service | Baseline ms (A) | Candidate ms (B) | Median A / B |
|---|---|---|---|
| data-health | 22480.315,16346.690,12640.646 | 593.771,445.408,552.132 | 16346.690 / 552.132 (-96.6%) |
| metric-coverage | 4767.582,2400.440,2656.200 | 2391.759,2211.936,2238.268 | 2656.200 / 2238.268 (-15.7%) |

All 12 results equal the baseline exactly. Data-health includes 406 sources;
metric coverage includes 87 names. Prices retain the old group-by path.
This is uncached service measurement, not a claim about browser load times.

Tenant defense-in-depth was then added explicitly to both margin functions,
for models AND outputs. The global ORM hook already adds tenant criteria to
entity and column reads; no actual production disclosure was demonstrated.
A regression covers foreign-tenant models, malformed cross-tenant outputs and
a newer foreign-tenant version. The deliberate malformed fixture uses Core SQL,
not an ORM tenant mutation, which is correctly rejected by the write guard.

A second ABBAAB for metric-coverage with the final explicit predicates gave:
A 2609.490,2749.143,2877.100 ms; B 2645.948,2260.868,2240.976 ms.
Medians 2749.143 / 2260.868 ms (-17.8%), all six results exactly equal.
Both runs exited 0. Full query/timing evidence is in the adjacent evidence files.

Plan comparison on PostgreSQL17 additionally confirms two independent issues:
`is_reported IS TRUE` does not imply the existing partial index predicate;
`is_reported` or `= TRUE` does. The redundant full INTEGER company-ID lower
bound is also required for the desired ordered Index Only Scan on this instance.
No database schema, indexes, planner settings, memory or tenant data changed.
Final targeted regression suite: 70 passed; Ruff clean. Existing 2722 guards
had passed before the explicit tenant-only hardening; recheck remains CI-gated.
