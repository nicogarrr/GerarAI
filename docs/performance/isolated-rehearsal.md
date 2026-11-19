# Isolated preparation rehearsal, inspection stage

This change adapts the historical preparation runner's missing safety preflight.
It does **not** include or enable a runnable serial/overlap benchmark yet. No
Docker resource or slice is created, no database command is run, and no build,
restore, rollout or cleanup is invoked. `rehearsal_preflight.py` only uses Docker
list, inspect and info against the local `/var/run/docker.sock`, reads host
cgroup/proc files and writes one private exclusive inspection receipt.

Keep the historical scripts as reference only. Do not launch them: backup
implicitly selects production and a global lock; image migration reads the live
schema and inserts obsolete version 0136; build outputs use deployed tags.

## Provenance and unchanged gates

The source for this design is the sanitized historical runner for cut
`6b2b0e6c532dfc891b58cb84fac32d33b92bb3a5`, exported 19 November 2026 by its
operator. Its operational scripts lived outside Git; the cut SHA does not
attest those scripts. The export has a manifest with individual original and
sanitized SHA256 values. No operational export, environment or credentials
are committed in this change.

The existing deployment gates remain: full VM suite on exact SHA, fresh backup
actually restored in isolation, matching exact front/backend SHA, image/schema
checks and explicit rollout approval. An inspection receipt is none of these.
Both rehearsal_authorized and release_authorized are always false.

## Operator-created inventory, no defaults

The Pilot must first create an isolated PG17 source from the already verified
dump, never by querying live production during rehearsal. This setup has NOT
happened and this PR does not authorize it. Strict restore must use
ON_ERROR_STOP=1 and a single transaction; restore input must be read-only. The
Pilot records dump SHA256, restore proof, actual schema version/table inventory,
source image ID and immutable full container/volume identities separately.

`rehearsal_guard.py` requires all and only these version-1 inventory fields:

| Field | Required value/evidence |
| --- | --- |
| schema | 1 |
| run_id | Unique lowercase letters/digits/hyphens, 8-48 characters |
| source_id | Full 64-hex container ID, never a name/prefix |
| source_image | Immutable local sha256: image ID |
| source_volume | Explicit inventoried local data volume name/ID |
| production_ids | Nonempty full-ID denylist, compared to fresh all-container listing |
| root | /home/ubuntu/benchmarks/gerarai-6b2b/RUN_ID |
| output | ROOT/serial or ROOT/overlap, existing directory |
| lock | ROOT/backup.lock, existing private file owned by the operator |
| cgroup_parent | gerarai_bench.slice |
| cpu_max | 200000 100000 |
| memory_max | 8589934592 |
| memory_swap_max | 1073741824 |
| sha | Full 40-hex SHA of clean source checkout used for inspection |
| source_db | bench_source |
| source_version | Actual restored version, not hardcoded 0136 |

These fields are inputs to compare against current inspection, not proof of
restore provenance. source_version and source_db are constrained inputs, not
SQL-queried content attestation. There is no environment, URL or password field.
Do not add secrets to inventory or receipts. The full database dump is sensitive;
keep it on the VM in its protected location, not in this repository or report.

Source ownership labels must equal `io.gerarai.bench.run_id=RUN_ID` and
`io.gerarai.bench.role=source`. Its data volume must carry the same run label
and role `source-data`; the setup adapter must arrange a freshly allocated
local volume with those labels, not reuse an unlabelled volume. An explicit
allowlisted identity, not its name or a label alone, binds it to this run.

Fresh inspection checks image ID, full source ID, denylist, labels, network none,
no published ports, no added privileges/devices/shared namespaces, no inherited
volume source, no external DB/service URL variables, and exactly the inventoried
data volume at /var/lib/postgresql/data. No source bind mounts or socket. Local
volume driver options must be empty and inspected mountpoint must match.
Every other container, stopped ones included, is checked for sharing the source
volume. Docker-data bind mounts on other containers cause conservative refusal.
Incomplete production inventory or missing/changed source fails closed.

## Resource proof, not flags alone

The Pilot's proposed budget is cgroup v2 with Docker's systemd driver and an
operator-created dedicated top-level gerarai_bench.slice. Other cgroup modes
are rejected. The source's HostConfig.CgroupParent, real host PID membership
and actual cpu.max, memory.max and memory.swap.max must all match inventory.
A different limit, even a smaller one, invalidates this comparison's manifest.

Preflight reads cpu.stat, memory.current, memory.peak, memory.events and io.stat.
It rejects any other live workload inside the slice, including unlabelled
helpers and direct processes in the parent. This is a point-in-time inspection,
not evidence of resource membership during a future benchmark. It reinspects
the source before writing its receipt and rejects configuration/PID changes.
The subsequent executor must revalidate throughout execution and collect all
workload PIDs, including dump, compression, restore, migration and actual build
workers. This change has no such executor and makes no duration-wide claim.

IOWeight is not an IO ceiling. No IO ceiling is enforced by this proposal;
io.stat is measured only. The shared Docker daemon is outside the slice and its
overhead is not covered by these aggregate limits. Shared VM load, page cache
and daemon effects are confounders to record, not hide.

## Running the inspection after a separate setup approval

Requires Python3.10+, Git, local Docker inspection access and readable host
cgroup/proc files. Run from the clean exact SHA of this PR or its audited merge.
Use explicit inventory, repo and receipt paths:

```sh
python scripts/ops/rehearsal_preflight.py \
  --inventory /private-audit/run-inventory.json \
  --repo /isolated/exact-source \
  --receipt /home/ubuntu/benchmarks/gerarai-6b2b/RUN_ID/serial/preflight.json
```

RUN_ID is a template, not an existing resource. The command creates no directory
or lock. It refuses missing paths, symlinks, output outside the dedicated run,
wrong lock owner, writable/shared lock inode, held lock and receipt reuse.
Receipts are 0600 and contain selected identities/counters, never raw Docker
inspect environment data. Failed inspection cannot create a green receipt.

## Remaining executor PR before any benchmark

The following work is deliberately **not enabled** by this inspection change:

1. Adapt actual dump/compression and strict restore into fixed, reviewed
   commands operating only on the inventoried source, own destination IDs,
   labels, networks, volumes, output directory and lock. No defaults to
   cavaai-postgres, global lock or old backup paths. No rotation of old dumps.
   Check inventory before and after each operation, including its cleanup.
2. Adapt historical source-replacement backend build with immutable base image
   identity and exact dependency/Dockerfile equality checks. Export only the
   exact tracked source into build contexts, never ignored secrets. Use new
   per-run/per-mode image tags, refuse existing tags and never push images.
3. Prove build workers themselves are descendants of the common slice.
   Docker's legacy image-build reference documents cgroup-parent for RUN and
   DOCKER_BUILDKIT=0. Availability on this VM is unverified. Modern default
   build is not assumed equivalent. A builder probe is useful but does not
   replace evidence for real build workers. If any worker cannot be inspected,
   abort instead of accepting a benchmark. Do not use the shared BuildKit.
4. A failed or interrupted Docker build can outlive its CLI. The executor needs
   audited daemon-side worker cancellation and cleanup restricted to this
   run's immutable IDs. Killing the local process group alone is insufficient.
   Never use broad Docker prune, name-prefix deletion or production slice kill.
5. Run isolated image migrations against schema read from the isolated source,
   retaining its real version. Do not insert 0136 or query the live schema.
   Record that a restored 0138 source tests 0138-to-head behavior, not 0136 DDL.
6. Serial must be default. Opt-in overlap is only backup dump→restore against
   backend build→frontend build→isolated image check. No heavy-suite overlap,
   rollout or switch. Failure cancels both lanes and cannot produce readiness.
7. Compare same snapshot, source SHA, dependency/image identities and aggregate
   resources. Declare cache state and order. A second cached build is not a
   clean A/B of concurrency. Do not flush host caches or prune shared cache.
   Record phase intervals, end-to-end time, peaks/events/IO and errors. Do not
   infer savings from synthetic sleeps or add ideal ceilings together.

Documentation checked 19 November 2026:
- https://docs.docker.com/reference/cli/docker/image/build/
- https://docs.docker.com/build/builders/drivers/docker-container

The docker-container Buildx driver only documents its driver-opt cgroup-parent
for cgroupfs, not systemd. Do not silently substitute that driver assuming it
respects the proposed slice. A separately implemented dedicated builder may be
acceptable only after proving actual process ancestry, containment and cleanup.

All tests for this change use synthetic Docker objects and local temporary
files. No Docker daemon, VM, production, provider or paid resource is used.
