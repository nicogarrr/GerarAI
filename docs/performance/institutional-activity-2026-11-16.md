# Complete stored institutional activity (PR A)

## Scope

Adds complete stored activity under `activity_role:all`, keeping the existing
`new_positions` contract and legacy role reader unchanged. Old snapshots without
the completeness marker return `sin_detalle` with unknown total, not zero.
A missing filing side yields null shares and change. Reported USD position value
is not transaction cash flow. Company ownership is null without a traceable
same-class, same-date denominator.

GET is SELECT-only, four SQL statements for a linked snapshot. No SEC refresh,
network call, write or queue dispatch is part of this endpoint. Filters are exact
states: increases/reductions exclude new positions/exits. All includes unchanged
and filing-missing states. Server-rendered UI uses one authenticated request per
page, 25 managers, query parameters, ES/EN, keyboard-focusable scroll region,
column/row headers and explicit filing date. Source and fetched date are shown.

## Evidence

- 91 backend focused/regression tests passed, including date-order, incomplete
  shares, mixed units, ownership routes and Watchlist new-13F query budget.
- Reader: 100% lines, 95% branches. Changed persistence service: 95.82% lines,
  94.44% branches (coverage.py combined figures 98.59% and 95.49%).
- 22 UI/action tests passed. Activity table: 100% lines, 93.93% branches;
  existing holders panel: 100% lines, 97.91% branches.
- Typecheck, ESLint (zero errors; six pre-existing unused-import warnings in
  company page), scoped Ruff, i18n, route and contract guards passed.
- OpenAPI generated using the real application exporter, then TypeScript
  generated with openapi-typescript. No hand edits to generated schemas.
- Actual component rendered with real Tailwind CSS and synthetic fixtures in
  Chrome at 1440 and 390 pixels, ES/EN. No page-level mobile overflow; table
  scrolls inside a 324px region (1123px content). No production user data used.

## Benchmark and limits

Evidence JSON files live in `docs/performance/evidence/institutional-activity-*`.
They are synthetic, local and not production/HTTP results. PostgreSQL version is
14.24, not production PG17. SQLite is explicitly separate. Seven cold-ORM reads
per scenario, with tracemalloc enabled. Reported p95 uses nearest rank (the max
of seven samples), not a high-confidence tail estimate. Fixture creation is
excluded. Python memory is traced allocation, not server/DB RSS.

Each page reads the entire linked snapshot: 1515 fact rows at 500 managers and
6015 at 2000. Four SELECTs, around 11KB for a 25-row response. Page 1, the final
full page (20/80), and an empty exact-state filter were measured. The JSON records
all samples, p50/p95 and peak memory. Tracing materially increases latency, so do
not compare these numbers with earlier uninstrumented samples.

Pagination is intentionally in memory for this first additive change. Its cost
is O(snapshot facts), including an empty filter. This is not claimed as database
pagination or a production performance improvement. A normalized activity table
or database-side grouping should be evaluated if the measured live workload
requires a lower latency/memory bound. No production performance/resource changes
are included.

## Not included

No PR B / September individual-filing discovery or refresh. No guarantee that an
existing production snapshot already has complete detail; it remains explicitly
unknown until the normal ingestion job rebuilds it. No new ownership denominator
inference. No deployment. Exact-SHA independent audit remains required.
