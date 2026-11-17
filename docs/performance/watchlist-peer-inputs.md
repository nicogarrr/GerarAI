# Online peer-input projection (alternative to unmerged #5819)

This replaces the proposed STORED-column design. It is **not** a migration to
run after that design and must not be stacked on top of it. Base is main
`6f1e0d9aac3fb2573897b87c36520c53be41d89c`, including fair-value projection #5820.
The original #5819 remains held. Neither this proposal nor its tests authorize
production work. Exact commit/tests require new audit review.

## Why the design changed

The Pilot measured the STORED-column rewrite on a restored production backup:
about 68 seconds blocking and about 989 MiB WAL. Those are reported copy-test
results, not measurements from this proposal or permission to run the rewrite.
The expensive calculation is unchanged, but it need not run under one long
table lock. The new design separates expansion, writes, reads and backfill.

1. Add nullable JSON column with **no default, generated expression or NOT NULL**.
   This does not rewrite existing rows. It still needs ACCESS EXCLUSIVE briefly.
2. Install a BEFORE INSERT / UPDATE OF output_payload, peer_rank_inputs trigger
   in the same migration transaction. Every new/changed output gets a projection
   atomically. Direct writes to the projection are recalculated too.
3. Read `COALESCE(peer_rank_inputs, valuation_peer_rank_inputs_v1(output_payload))`
   as one JSON array, not six repeated fallback expressions. PostgreSQL
   short-circuits the fallback when the column is filled. Old rows are correct
   immediately, even if backfill pauses for days. This is not a TTL cache.
4. Backfill only NULL projections in bounded row-lock batches. Commit each batch,
   throttle between batches and check pending rows separately. No long DDL lock
   or table rewrite is held for this phase, but it uses CPU, WAL, row locks and
   creates dead tuples. Writers touching the current batch may wait.

The projection preserves the same six raw JSON values and Python ADR/currency/
ratio rules as #5819. The latest-model window still selects insufficient-data
rows before its outer status filter. No older valuation is resurrected.
SQLite keeps its existing read path and has no migration action.

## Lock behavior and operational bounds

Migration 0136 sets a transaction-local `lock_timeout=250ms`. If an active reader
prevents the metadata lock, the migration fails and the transaction must roll
back. Do not catch and continue inside an aborted transaction. A waiting
ACCESS EXCLUSIVE request can queue other traffic for up to that timeout, so
this is **not zero blocking**, and 250 ms is not a production latency promise.
Release should also set a bounded statement timeout and commit immediately
once migration finishes. Do not do backfill or benchmarks in that DDL transaction.
There are no indefinite automatic retries in this proposal.

Old app code works with the extra column and trigger. New app code requires
migration first because it references both the column and projection function.
Roll app code back before dropping the column/function. Leaving the trigger/
column in place during an app rollback is safe and avoids unnecessary DDL.
Do not drop the trigger while the new reader is active: a formerly filled row
could otherwise become stale after an output update.

Both candidates have the same unmerged revision ID 0136. Select ONE design.
Do not merge both PRs. The online migration rejects an existing generated
column if called directly; Alembic will skip an already-stamped revision, so
Release must also inspect actual schema and migration history before rollout.
If STORED was applied anywhere, stop and plan an explicit conversion separately.

## Backfill contract

`app.valuation.peer_rank_projection.backfill_batch(connection, batch_size=25)`
executes one MATERIALIZED-CTE batch, ordered by output primary key, with
`FOR UPDATE SKIP LOCKED`. Batch size is an integer 1..100. The UPDATE sets the
projection to NULL only to invoke the trigger, which derives it once from the
current locked output. It never copies values from an earlier client snapshot.
The helper does not commit; transaction/timeout/throttle ownership is explicit.

Pilot run procedure after separately approved rollout and restored-copy test:

- Keep the old app running during expansion. Apply migration in its own short
  transaction with bounded statement timeout. Confirm non-generated nullable
  column, projection function and enabled trigger; verify no row rewrite in
  the restored-copy rehearsal. Then deploy exact reviewed new code.
- Start batch size 25, one short transaction per helper call. Set local
  `lock_timeout=250ms` and `statement_timeout=1s` on every batch transaction.
  Commit only successful batches. On error roll back that batch and pause;
  previous commits remain valid. Do not retry in a busy loop.
- Pause at least 100 ms outside transactions between successful batches.
  Increase pauses or reduce batch size if DB CPU, WAL, replica lag, application
  errors or writer latency worsen. Stop if resources or SLA are not acceptable.
  Even a 25-row batch can exceed a second on production hardware; the timeout
  is the guard, not the synthetic timing below.
- After each bounded run, check
  `SELECT EXISTS (SELECT 1 FROM valuation_outputs WHERE peer_rank_inputs IS NULL)`.
  An empty returned-ID list is NOT completion: all eligible rows may be locked
  by another transaction. If NULLs remain, pause and resume later. Re-running
  from the beginning is safe; no OFFSET/cursor checkpoint can permanently skip
  locked rows. Stop only when that separate pending check is false.
- No speculative index is added. The repeated NULL search scans increasing
  completed prefixes; measure actual table cardinality/scan cost on the copy.
  If that becomes a problem, return for a reviewed keyset/index design rather
  than invent an index during rollout.
- Compare old/new dictionaries for the same tenant/snapshot before and after
  partial/full fill. Confirm insert/update behavior and pending=0. Remeasure
  monitor SQL/HTTP/LCP, write latency, CPU and error rate with cold/warm labels.
  Do not run a full expensive parity scan on a loaded production server without
  its own measured budget. No cache invalidation or second code cutover is needed.

This proposal supplies the tested helper and run procedure, not an unattended
production backfill daemon. The Pilot owns bounded execution and follow-through.

## Local verification

PG14.24, Python 3.12.16, SQLAlchemy 2.0.46 (allowed by repository constraints,
not a lockfile-exact full-suite certification). All schemas are disposable.
No private production data or plans are included in the evidence pack.

- SQLite: 46 passed, 8 skipped (PG-only tests).
- Real PG: 54 passed.
- Wider fair-value and monitor/rank/route/pence regression: 145 passed, 8 skipped.
- Combined per-file coverage: relative_rank 97.56% lines / 100% branches;
  projection/backfill helper 100% / 100%; migration 100% / 100%.
- Ruff and diff checks pass.

Tests prove unchanged relfilenode after expansion, no synchronous backfill,
repeat upgrade/downgrade/re-upgrade, partial-fill read parity, trigger writes,
scalar/null/type/ADR/tenant/latest-status behavior, one SELECT and zero output
ORM loads. A DB fallback function replaced with an exception proves filled
rows never execute the full-payload fallback, rather than trusting SQL text.

Concurrency/failure cases:

- Writer owns row first: backfill skips it, fills other rows, then writer commit
  leaves the projection matching its new payload.
- Backfill owns row first: concurrent writer gets SQLSTATE 55P03 under its test
  lock timeout; retry after batch commit preserves the writer's newer value.
  This demonstrates correctness plus the bounded row-write delay, not no delay.
- Successful batch commit survives pause/disconnect. Rolled-back batch is still
  pending and is processed on restart. All-rows-locked empty batch is recognized
  as incomplete and succeeds after locks release.
- Reader holds table lock: expand hits 250ms lock_timeout, transaction rollback
  leaves no partial column/function. Retry after reader commits succeeds.
- Direct projection overwrite cannot detach it from source JSON. Conflicting
  generated-column design is rejected rather than silently accepted.

## Synthetic A/B, not production latency

467 companies, 1,218 models/outputs, tenant 5, alternating draft/insufficient
statuses, synthetic trace 640,000 characters/output. Exact same 233 ratios in
all variants and one SELECT per call. First calls separated; medians use the
next eight calls, not a controlled cold-cache experiment.

| Variant | First ms | Warm median ms | Pending outputs |
| --- | ---: | ---: | ---: |
| Frozen production-base query 75723d9 | 786.989 | 618.139 | n/a |
| Online, no backfill | 312.246 | 309.315 | 1,218 |
| Online, 600 filled | 216.310 | 215.827 | 618 |
| Online, complete | 3.149 | 2.860 | 0 |

Initial improvement comes partly from excluding insufficient rows after the
latest-model window. Full fill avoids parse work. Final EXPLAIN execution was
1.278 ms versus baseline 620.182 ms. Synthetic expand DDL work was 1.86 ms and
100-row backfill statements about 92-136 ms. These statements ran inside one
isolated benchmark transaction for comparison; that timing does **not** measure
committed backfill batches or real metadata lock hold time. Separate tests
exercise actual commit/resume behavior. Raw samples, plans and harness are in
the evidence pack. Pilot must measure committed batches, WAL/CPU, lock acquisition
and impact on real concurrent traffic on the restored copy before deciding.

## PostgreSQL 14 sources

- No-default ADD COLUMN avoids rewrite; ACCESS EXCLUSIVE still applies:
  https://www.postgresql.org/docs/14/sql-altertable.html
- BEFORE triggers, UPDATE OF semantics:
  https://www.postgresql.org/docs/14/sql-createtrigger.html
- SKIP LOCKED row semantics and remaining table locks:
  https://www.postgresql.org/docs/14/sql-select.html
