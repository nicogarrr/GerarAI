# Watchlist monitor: split query budget

Base main ac7490c7e66a9a397d404ef7295c45cc765674f5.
GET /api/watchlist/monitor repeated a count and a minimum-close query for each
company with a split in the last year. The replacement uses two batch reads:
a CASE with each company's last split date, GROUP BY count, and row_number
partitioned by company for the low. The per-company cutoff and rank=1 are in
SQL, not a Python trim after loading the history. No source, value precedence,
quote units, null handling or response fields changed. No network added.

## Measured, synthetic SQLite

The regression test counts actual SQL statements and MarketPrice ORM loads.
Fair value resolution is held out identically on both sides to isolate this
price path; PostgreSQL live latency and full DOM latency were not measured.

| Companies with splits | History/company | Before queries | After queries | After price objects |
| --- | --- | --- | --- | --- |
| 1 | 30 | 8 | 8 | 1 |
| 20 | 30 | 46 | 8 | 20 |
| 60 | 300 | 126 | 8 | 60 |

Original source restored temporarily from base and tested with the same final
regression tests: the 20/60 query budgets fail; the 1-company and boundary case
pass. Optimized source restored and all four pass. Loaded objects remain
bounded even with 18,000 price rows. Tests cover differing split windows,
last of multiple splits, future/old splits, zero prices and no post-split data.

This does NOT explain the Pilot's reported 12.77-second production DOM load.
It removes a measured N+1 on one path, not a verified end-to-end bottleneck.
No production access, merge, deployment or paid call in this work.

## Validation

Run sh scripts/test-watchlist-split-budget.sh. Full touched source coverage:
660/684 lines (96.49%), 121/138 branches (87.68%). Ruff and focused Pyright
pass with zero errors/warnings. One existing PostgreSQL-gated test skips in
this environment. Production PostgreSQL comparison remains a deployment gate
for Pilot, not a latency improvement claimed here.
