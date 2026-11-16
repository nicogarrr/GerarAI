# Cold portfolio snapshot read budget

Base f2ed2be. Snapshot accesses Position.company lazily in a loop. A cold
identity map performs1+N SELECTs on an uncached call. joinedload on that
many-to-one relationship folds company reads into the existing positions query.
No cache key/TTL, totals, currency interpretation, filters or payload changed.

Real SQLite ORM counters, not timings. Same ensure_portfolio stub and cache
bypass both sides. N=0/1/20/60: before1/2/21/61queries, after1/1/1/1. ORM loaded
Position and Company counts remain0/1/20/60 each; no hidden broad company load.
A second portfolio with one extra holding is excluded from all outputs/loads.
A separate fresh Session prevents the seed identity map from masking the N+1.

47 tests pass (new budgets, cached data edges, tenant fail-closed, Redis caching,
integration user flows); touched source100%lines100%branches. Ruff clean.
SyntheticSQLite only, not production latency. No calls to paid services/deploy.
The valid baseline test commit is ae6f156 (a84e176's initial fixture lacked
required company fields and was corrected before measuring performance).
