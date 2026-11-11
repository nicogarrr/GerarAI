# KPI consumer recovery

No queue deletion or replay script is part of this change. Only the deployment
owner operates production, one check at a time.

## Evidence, 11 November 2026 19:54 CET

The deployment owner reported 500 persisted messages: 496 ready and 4 stale
acks; 489 extract_document_kpis and 11 recompute_fundamental_metrics, no retries,
156-158 hours old. A document-ID existence check does not validate the arguments
of recompute_fundamental_metrics. Snapshot retained by the deployment owner.
The removed worker exited 137 on 5 November, OOMKilled=false; cause unconfirmed.
Host MemAvailable was 14334 MiB; other process peaks do not measure KPI memory.

## Candidate resources and health

Restore the existing dedicated service with 1 process, 1 thread, prefetch 1/1,
CPU 0.40 and a 1 GiB memory limit. The limit is a bounded starting candidate,
not a measured heavy-extraction requirement. Do not change other services.
Validate RSS/peak and restart counters on a small initial batch before full
drain. If it nears the limit, stop KPI and investigate loading/chunk sizes.
Do not claim exit137 proves OOM or raise resources without host validation.

A queue-specific lease is renewed only after successful polling by the KPI
consumer. The admission check and depth cap run in the same Redis Lua script;
Redis time is authoritative. Default/new-ingestion admission is 100; existing
accepted messages above that cap remain consumable. Retry and delayed promotion
paths remain native and are not rejected. Missing consumer or Redis failure
leaves durable document-deferred metadata for later backfill.

The healthcheck uses the local worker's token, not another worker's heartbeat.
Lease expiry is 60 seconds, so detection is bounded, not instantaneous. Polling
health does not prove task progress. Monitor completion rate, oldest-ready age,
RSS, restarts and 429s separately; retain the queue watchdog's progress checks.

## Drain, do not purge

1. Preserve the owner's recoverable snapshot and verify per-actor arguments,
   ownership, active tenant and current persisted results before selective work.
2. Allow native broker maintenance to reclaim stale acks after heartbeat expiry.
   Never delete ack sets by hand. Existing extraction candidates already make
   extraction idempotent; do not regenerate approved/rejected observations.
3. Drain valid work with one thread. For duplicates require equivalent persisted
   results; for deleted tenants/documents or malformed arguments, quarantine IDs
   and reasons, never delete source documents. Age alone is not a discard rule.
4. Keep the effective 20 LLM attempts per tenant per UTC day and provider setup.
   Exceeded quota remains deferred until the next UTC day. Do not reset usage,
   increase quota or enable a paid provider. The 11 metric recomputes have a
   different workload and must not be treated as document IDs or LLM calls.
5. Stop and report on failure; preserve messages and diagnostics. The historical
   7711 dead letters are outside this rescue, with no blanket replay or purge.

A 500-message backlog cannot be promised to finish today: its runtime depends
on valid work, tenants, documents with existing results and the effective quota.
