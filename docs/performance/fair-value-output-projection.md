# Fair-value output projection

Independent follow-up to the peer-universe read fix. Base:
`75723d9f7c5482900e80d1728f5db11e7237d558`. No migration and no dependency on
peer-input migration 0136. No change to financial values, source precedence,
ADR rules, missing-data reasons, draft expiry or thesis freshness.

## Grounding

The Pilot's read-only production profile, 17 November 2026 at 13:02 Madrid,
measured the warm `resolve_fair_values` call at 272 ms and
`persisted_engine_readings` at 246 ms wall time (222 ms profiled cumulative).
`json.loads` consumed 193 ms across 80 calls; output JSON totaled 15,375,638
bytes across 32 outputs for 12 companies. These are separate-process profile
measurements, not HTTP latency. Expired Company reads contributed about 22 ms.
The first call's 2.1 s thesis-service/Qdrant import is cold-start work, not a
warm Python-rule cost. Raw production artifacts are not committed.

## Change

Select output model ID and only the six top-level JSON fields actually read:
`listed_share_values`, `adr_ratio`, `expected_value`, `base_value`,
`estimated_inputs`, `valuation_label`. Keep JSON types, including whether
`listed_share_values` is a dict, so the ADR missing-value reason is preserved.
PostgreSQL uses one lateral `json_to_record` parse per output; SQLite uses its
existing JSON projection operators. Rebuild a small payload for the unchanged
value/metadata helpers instead of materializing ValuationOutput entities and
unrelated traces. The latest-model window and model/block handling are unchanged.

The complete `listed_share_values` and `estimated_inputs` objects are retained
for semantic fidelity. If those fields themselves are unusually large, the
projection is not a constant byte cap. It excludes unrelated top-level fields
such as calculation traces, not every possible nested field.

## Synthetic A/B

Python 3.12.16, SQLAlchemy 2.0.46, PostgreSQL 14.24; random disposable schema,
12 companies, 32 outputs with a 480,000-character synthetic trace each. Both
paths run in one session, expunging ORM identity state before every sample,
with exactly equal Candidate/EngineBlock/gap results. No external providers.

| Variant | First call ms | Median of next 8 ms | JSON bytes passed to decoder/call | SELECTs |
| --- | ---: | ---: | ---: | ---: |
| Frozen full-output base | 52.389 | 38.842 | 15,363,352 | 2 |
| Projection | 29.730 | 27.092 | 920 | 2 |

This is a local synthetic result, not a prediction of production savings. One
projected sample was 99.544 ms; all samples are retained in the evidence pack.
The optimization shifts work to the database: EXPLAIN execution of the output
query rose from 0.015 ms to 24.696 ms because the latter parses JSON server-side.
EXPLAIN does not include full-payload client transfer/decoding in the baseline.
The net local call improved by about 11.75 ms, not by the whole client decode
cost. Check DB CPU/concurrency and actual HTTP latency before accepting rollout.

## Tests and gates

- New comparator/byte/counter tests: 25 pass on SQLite and 25 pass on real PG.
- All fair-value tests plus monitor/batch/nonblocking/rank: 98 pass.
- Expanded set including monitor route and pence handling: 107 pass.
- Frozen old implementation compares complete candidates, blocks and gaps,
  including malformed/scalar/null JSON, ADR and listed-value precedence,
  metadata types, latest insufficient-data rows, tenants 2/5, missing models,
  missing outputs and multiple scenarios.
- Byte assertion: unrelated 1 MB trace decoded on old path, under 2 KB on new
  path. Two SELECTs, zero ValuationOutput ORM loads on new path.
- Per-file combined SQLite+PG coverage: `fair_value_service.py` 94.12% lines /
  86.62% branches; `fair_value_projection.py` 100% / 100%.
- Ruff and diff checks pass. No dependency files changed. Environment is not a
  lockfile-exact full-backend-suite certification.

Evidence pack contains raw samples, synthetic EXPLAIN plans, harness, test
reports and coverage JSON/config. Harness runs from `data-engine` with
`PYTHONPATH=.` and `PEER_RATIO_TEST_PG_URL` pointing only to a disposable database.
It creates a random schema through the shared test fixture and drops it after.

## Rollout gate

Review exact commit and tests first. Pilot alone executes any authorized
production rollout. No schema operation is needed. Can be reviewed/cherry-picked
independently of the peer-universe fix. Before/after should keep tenant,
watchlist, process warmth and Company identity state comparable, and record
HTTP monitor latency plus DB CPU/error rate. Roll back code if the DB parse
shift is a regression under real concurrency. No production action was taken
as part of this proposal.
