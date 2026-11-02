# Portfolio intelligence projection audit

Production-volume, read-only repeatable-read tenant2, deployed baselinefc6478e8,
candidate loaded from /tmp, no app replacement and no backup concurrent. Fixed
clock, expunge identity map and GC before every round; tracemalloc on for both.
One shared live benchmark cache isolates network variation (the first round
fetches once, subsequent rounds reuse exactly the same response). ABBAAB repeated
twice. All12outputs equal exactly, including return/exposure/benchmark values.

Second run (ms): A2058.786,B727.653,B708.095,A717.678,A699.480,B717.037.
Exclude the first cold network round from a warm latency claim: there is NO
stable meaningful latency improvement (warmA median708.579,B717.037).
The first run gave warmA790.165 vsB770.984, also too small/variable to generalize.

The intended, measured benefit is bounded ORM hydration and memory, not faster
portfolio calculations. Snapshot entity loads41→0 each round; warmed tracemalloc
peak9,181,517–9,181,637bytes(A) vs9,125,281–9,125,426bytes(B), ~0.6% lower.
This production tenant has only41snapshots, not the1250used by the original
synthetic test. No storedSPYbenchmark exists here, so its column projection is
covered by the fixture regression rather than falsely reported as prodmeasured.

The upstream PR3713history is preserved in this integration branch. Snapshot
history endpoint semantics remain untouched. Final44portfolio/snapshot/risk/
benchmark regressions pass plus the earlier126integration tests; Ruff clean.
No portfolio/transaction/order was changed by measurement. No schema or global
planner setting changed. Evidence file includes complete per-round counters.
