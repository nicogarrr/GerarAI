# Peer-ratio JSON projection

Baseline: `337b41006cca7b7fc4f1707a6400573b00838e9e`.

`engine_peer_ratios` needs six JSON values, not each full valuation trace. On PostgreSQL, two guarded `json_to_record` lateral records keep JSON types and project only those values. Other dialects use JSON field access. The existing Python `listed_value` and `_ratio` rules, tenant predicate, latest-version selection, statuses and company universe stay unchanged. There is no cache.

## Restored PostgreSQL A/B

Run by the deployment operator on the same PRE337 dump, isolated PostgreSQL with 1 CPU / 1 GB, and one backend image. Each call uses a fresh session with `SET TRANSACTION READ ONLY`. The script embeds the baseline and candidate functions and switches only the peer-ratio function in its own process. No startup, migration, schema change or production execution.

After a separately labelled initial pass, warm order is A, B, B, A. Only two warm observations per variant: these are diagnostic measurements, not a production benchmark or a statistical latency estimate.

| Warm metric | Baseline A | Projection B |
| --- | ---: | ---: |
| Ratios wall time, samples (ms) | 7123.73, 7772.62 | 2441.18, 2375.74 |
| Ratios wall time, mean (ms) | 7448.18 | 2408.46 |
| Ratios client process CPU, mean (ms) | 7079.81 | 11.47 |
| Ratios SQL execute, mean (ms) | 426.52 | 2398.03 |
| Ratios decoded JSON bytes/call | 318362440 | 25383 |
| Monitor wall time, samples (ms) | 7470.74, 7338.77 | 2551.08, 2906.51 |
| Monitor wall time, mean (ms) | 7404.76 | 2728.80 |
| Monitor SQL execute, mean (ms) | 359.07 | 2346.28 |
| Monitor decoded JSON bytes/call | 333835074 | 15498017 |

Mean warm wall time fell 67.7% for ratios and 63.1% for the monitor in this restored-data experiment. This shifts work to PostgreSQL: SQL execute time rises substantially. SQL timings overlap wall time and must not be added to it. Client CPU is process CPU, not total database CPU.

All baseline/candidate ratio digests match across all calls (217 ratios); all monitor response digests match (12 items, 10 SQL statements). Query counts and universe are unchanged. Initial cold monitor times are deliberately excluded from the warm comparison. Cold imports are not part of this change.

## Counterexample and limitations

A local synthetic PostgreSQL 14 dataset with 40 mostly flat 250 KB payloads regresses: ratios 19.75-20.46 ms to 28.09-28.39 ms; monitor 34.46-35.06 ms to 42.85 ms. It still reduces decoded peer JSON from 10002800 bytes to 240 bytes and client CPU from 17.44-18.52 ms to 1.42-1.57 ms. Do not infer a universal improvement from fewer bytes.

An earlier six-operator JSON extraction candidate was discarded because PostgreSQL reparsed large JSON repeatedly and ratios took about 131 ms. It is not the submitted implementation.

## Validation

- Red first: the large-payload test fails on baseline because 1250126 bytes are decoded.
- 27 equality/type/large-payload tests pass on SQLite and real ephemeral PostgreSQL 14, including tenant 2/5, latest draft/insufficient data, minor currencies, null/non-object JSON, ADR truthiness, listed-value precedence and bounds.
- Explicit tenant filtering is also tested with Core execution that bypasses the redundant ORM loader-criteria hook.
- Combined local regression run: 98 passed, 1 PostgreSQL fixture skipped, 1 existing Pydantic deprecation warning. Separate 27-test PostgreSQL run passes with warnings treated as errors.
- Local provisional `relative_rank.py` branch coverage: 98.10% (83/85 statements and 20/20 branches). Official coverage remains the auditor's measurement.
- Deliberate mutants removing ADR handling, swapping listed-value precedence and removing the explicit tenant predicate each fail their test.
- Ruff and repository Semgrep rules pass; no findings.

No merge or deployment is included. Exact-head auditor approval is required before merge. Deployment and any production measurement belong to the deployment operator with coordinator approval.
