# Disposable CI admission measurement, DO NOT MERGE

Base: admission queue 9d1aa73d1. This commit is a measurement harness, not product telemetry.
The workflow runs ficha + first-steps on desktop/mobile with one worker and uploads:

- data-engine/storage/admission-ci.jsonl: backend gate attempts/admissions/final status.
- test-results/admission-cases.jsonl: hash-to-test-name mapping, retry and worker.
- test-results/admission-summary.json: per case/attempt counts and concurrent peaks.

The factory refuses to start without both APP_ENV=test and E2E_ADMISSION_TRACE=1.
A random process-only salt pseudonymizes tenants consistently within the run.
No headers, cookies, body, query string, tenant identifier or salt are written.
Only random request IDs, method/path, pseudonym, counters, monotonic times and status.
The request end is recorded after ASGI/dependency cleanup, not at response headers.
Only requests that enter the admission gate are counted, not every HTTP endpoint.
Preliminary attempt/admitted events have status 499 as an unfinished sentinel. Use
end events for actual final status. Cancelled requests remain 499.

Awaited Playwright markers bracket fixture/test activity. Backend capture includes
Next SSR/server actions too, even when absent from browser network logs. Case windows
are temporal attribution, not proof a particular browser caused all traffic.
initial/final inflight and carry-in/out expose spillover. If teardown never marks end,
the summary marks incomplete_window and uses the last event as an observation cutoff.
Do not treat that cutoff as completed cleanup. Unclosed requests stay explicit.
Peaks include carry-in requests. completed/status counts follow eventual ends of
requests begun in the window, including an end after its closing marker.

Local validation: 16 probe/queue tests pass; 156/156 probe+summary statements,
21/22 branches covered (probe 13/14, summary 8/8). A broader earlier admission run
passed 25 tests before adding the last two probe tests. Ruff and diff whitespace clean.
Probe tests cover rejection, cancellation cleanup, stable pseudonyms/no sensitive
input leakage, factory guards, non-HTTP/background pass-through, 500 and carryover.
Frontend dependencies are not installed in this worktree: full typecheck and actual
browser/CI replay remain for Frontend before any conclusions about real concurrency.
