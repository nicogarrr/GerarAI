# common_sessions: count rows without DISTINCT

Base: `20f36dbd2ae1f46a987816938c2edb87db75db73`.

## Observed production shape, not a production A/B

The Pilot supplied a slow-query summary for 2026-11-18 05:00 to approximately
08:54 Europe/Madrid, threshold 1 second, under gate workload: 74 records and
7 truncated SQL shapes. The fully visible market_prices grouped-date query
occurred 32 times, total 91.105 seconds, maximum 5.145 seconds. That is about
58% of the recorded elapsed sum, not a measure of all database work.

The exact shape maps to `market_change.common_sessions`. Its application
callers are `compute_session_changes` and `ticker_close_change`. These feed
`/api/market/movers`, `/api/market/changes` and the company price fallback.
The log does not say which caller issued each occurrence.

Other shape mapping: grouped FinancialFact company counts match
`CompanySnapshotService._counts_many`; the multi-scalar count projection
matches its `_counts`. The full FinancialFact entity shape is truncated
before its filters and has many possible callers. The row_number shape has
multiple candidates and cannot be uniquely attributed from the provided
prefix. Neither is treated as a confirmed endpoint attribution.

## Safe simplification

`market_prices.company_id` and `date` are NOT NULL and protected by
`uq_market_price_company_date`, declared in the initial migration and model.
The common-session query has no joins. Within each date there can be only
one row per company, even across different sources. COUNT(*) therefore
matches COUNT(DISTINCT company_id) exactly. All source/date filters, ordering,
LIMIT 30, weekday selection, median and threshold logic are unchanged.

No index, schema migration, cache, materialized aggregate or new query is
added. The production unique constraint and its valid backing index must
be confirmed by the operator before relying on this invariant there.
The model alone is not proof of the live database schema.

## Local PG experiment

Synthetic fixture: 1,500 companies x 1,250 calendar dates = 1,875,000 prices,
80% yfinance and 20% finnhub, warm database cache, local server. Production
cardinality/source mix have been requested but are not yet available; this
is not claimed to be a production-size replica.

30 fresh-query alternating A/B pairs, same connection/database, row output
compared before measurement, nearest-rank p95:

| Query | Median | p95 |
|---|---:|---:|
| COUNT(DISTINCT company_id) | 8.195 ms | 10.200 ms |
| COUNT(*) | 4.527 ms | 4.988 ms |

Separate EXPLAIN ANALYZE BUFFERS observations, not the timing distribution:
11.991 to 6.288 ms, 910 to 880 shared-hit buffers. The original plan already
uses the date index and stops after 30 groups. It does not scan all history
in this fixture. Removing DISTINCT removes the incremental company-id sort.

A source/date/company covering index was also tested then rejected from the
patch: around 69 MiB additional index for this fixture, further local gain
only about 1.6 ms p95. Its write cost, production build time, lock behavior
and workload value were not measured. No such index is proposed or created
outside the disposable benchmark schema.

Local cache/hardware/planner conditions differ from the gate workload. This
patch does not establish a production improvement, explain the whole 1-5s
production timings, or prove that production would choose the same plan.
Cold cache, concurrent load, HTTP p95, write throughput and production
resource use remain unmeasured.

## Tests and evidence

`test_common_sessions_row_count.py` compares both algorithms over 10 seeded
universes with gaps, source differences, weekends and future rows, captures
SQL to ensure one COUNT(*) query, and verifies the database rejects a second
source for the same company/date. All 11 tests also pass against disposable
PostgreSQL. Schemas are removed in finally.

The directed existing market/currency suite passes 95 tests with one existing
Pydantic warning. Whole market_change.py: 96/97 lines (98.97%), 36/38 branches
(94.74%), combined 97.78%. Remaining branches are unrelated to this change.
No claim is made about the entire repository suite.

Command from data-engine (use the project Python environment):

```sh
APP_ENV=test python -m pytest tests/test_common_sessions_row_count.py tests/test_market_change*.py tests/test_market_movers.py tests/test_market_session_coherence.py tests/test_movers_cache.py tests/test_quote_unit_consumers.py tests/test_lse_paris_quote_currency.py --cov=app.services.market_change --cov-branch --cov-fail-under=85 --cov-report=term-missing --cov-report=json:/downloads/common-sessions-coverage.json
```

For PostgreSQL test execution set COMMON_SESSIONS_TEST_PG_URL to a disposable
database with schema creation permission, then run just the new test file.
Without it the fixture uses SQLite. Never point this harness at production.
