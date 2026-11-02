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
