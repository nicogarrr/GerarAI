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
Missing denylisted production IDs or missing/changed source fails closed.
The denylist is verified by the Pilot. This code does not discover or classify
all production containers: an additional unclassified container without
conflicting mounts or slice occupancy can pass. Completeness of the production
classification depends on the Pilot, not this listing check.

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

## Offline build workers, library stage

`rehearsal_build_workers.py` and `rehearsal_docker_build.py` now provide the
worker-control portion of the future runner. They have no CLI and are not wired
to a benchmark, source setup, live script or CI. The complete backup/build A/B
runner is still pending. Importing either module performs no Docker operation.
Only the Pilot may exercise the actual backend on the VM after exact audit and
separate execution approval. Current tests use fake HTTP/proc objects plus one
local shell test. They do not prove the VM supports this backend.

The selected experiment is explicitly **warm dependencies, offline compilation**.
Both arms must use identical immutable local base/dependency images produced
once before measurement. It is not comparable as the same workload to the
historical build, which ran apk and npm ci. The frontend derivative removes
only the exact reviewed apk/npm-ci instructions and substitutes pinned local
base/deps IDs. It retains `npm run build`. The base/deps images must have all
three exact SHA256 fingerprint labels, suffixes `lockfile`, `install-hooks` and
`dockerfile` under `io.gerarai.bench.deps.`. The caller must compute these from
package-lock.json, scripts/install-hooks.mjs and Dockerfile in the clean exact
checkout. Matching labels bind explicit image IDs to the Pilot's build record;
labels by themselves do not prove the image's contents. The Pilot must retain
one-time dependency-layer production and provenance evidence separately.

Every shell-form RUN gets an independent gate file with a random per-build UUID
and per-step suffix. A gate cannot persist from an earlier RUN or prebuilt base.
The gate waits at most about 60 seconds for approval, otherwise exits125 before
the original command. Its counter loop runs in a subshell; a failed gate exits
the parent before any original body, while successful gating leaves shell
variables and exported environment unchanged (including an existing n). Unsupported Dockerfile constructs, parser directives,
ONBUILD in external bases, base volumes/custom shells, dynamic FROMs, exec-form
RUNs and ownership-label overrides are rejected rather than loosely rewritten.
External FROMs are replaced with local immutable image IDs; COPY --from may
reference only declared local stages. Inherited entrypoints are cleared after
every FROM so they cannot run before a gate. No remote frontend or context is
supplied. Each RUN's original shell short-circuit/exit behavior
is retained after release. The generated images contain gate files and are
benchmark-only artifacts, not release images.

Before releasing a worker, the host controller checks its full immutable ID,
non-production/non-source identity, exact run/build/recipe/step labels and
expected gated command. It checks HostConfig.CgroupParent, namespaces,
privileges, absence of host mounts/socket/volumes, real PID cgroup membership
and current aggregate limits. It also checks NetworkMode=none and reads the
worker's actual /proc/PID/net/{dev,route,ipv6_route}: only loopback, no usable
default route. A reject-only IPv6 ::/0 loopback route is not a usable default.
The backend repeats these checks immediately before writing only the gate file
inside that exact worker using a root exec with a positional filename. No
unreviewed shell body or user-supplied Docker option is interpolated.

The local backend uses the Docker Unix socket directly with the legacy build
API's version=1 selection, pull=0, nocache=1, networkmode=none and the dedicated
cgroup parent, plus the reviewed per-build resource flags. It cannot fall back
to shared BuildKit. It refuses existing output tags/workers. The supplied tar
must contain a unique generated recipe matching the expected SHA256; absolute,
traversing, symlink/special or environment-file entries are rejected. Packaging
only exact tracked build inputs, validating output paths and checking local
base presence before submission remain the caller's required responsibilities.
No registry credentials or inherited Docker context/config/proxy are sent.

Cancellation is a daemon operation, not a local CLI signal. The backend keeps
the build HTTP request open, stops granting gates and repeatedly kills only
owned, uniquely gated worker IDs, including late workers. It requires a terminal
daemon success/error frame followed by clean HTTP stream completion, and no live
owned worker afterward. CLI exit, an intermediate progress message, transport
loss or an empty instantaneous list cannot produce cancellation confirmation.
After90seconds without positive completion it reports unconfirmed cleanup.
The controller stays non-green in every failed/interrupted case. A clean build
also requires proof for every RUN and a fresh final image ID/tag/recipe check.

No broad resource deletion is implemented. Dead intermediate containers/images
are retained for the Pilot's ID-scoped follow-up, not pruned automatically.
A process hard-kill, host failure, lost Docker connection or broken backend can
still require operator follow-up. Cgroup limits bound admitted work, not the
shared daemon's context transfer/COPY/commit/tag overhead. That overhead remains
outside the slice and must be reported as a confounder. The per-RUN approval
poll adds overhead; do not report those timings as an untouched production build.

Reference implementation checked for API parameter names and response behavior:
- https://github.com/Moby/moby/blob/v28.5.2/api/server/router/build/build_routes.go
- https://github.com/Moby/Moby/blob/v28.5.2/builder/dockerfile/builder.go

This source inspection is not a claim about the VM's installed Docker version.
The first VM exercise must be a separately approved tiny local-image offline
build with an intentionally failing/interruptible RUN. Confirm actual workers,
network/cgroups, terminal response, no late live worker after cancellation and
scoped residue inventory before attempting the large build/backup comparison.

## Exact committed input packaging

`rehearsal_context.py` prepares a local tar and separate manifest from
`git archive` on the full clean SHA. It never reads ignored/untracked working
files as build inputs. Backend context strips the data-engine/ prefix; frontend
retains the committed .dockerignore for daemon-side filtering. Tracked symlinks,
special files, traversing/absolute paths, environment files and generated-recipe
collisions are rejected or explicitly omitted. The generated gated recipe has
its own SHA256 and is never mislabelled a committed blob.

The tar manifest includes *all tar inputs*, not merely effective Docker image
files. Docker may ignore more paths. It records per-input hash, tree/SHA,
generated recipe hash and streamed archive hash, and never authorizes release.
Both tar and manifest are created exclusively0600 outside the checkout; the
caller must use its validated private per-run output directory. On failure a
partial tar can remain, but no completed manifest is created. Never treat tar
existence alone as successful packaging. No cleanup rotates old artifacts.

This module does not yet add a CLI, start a build, certify hot-image provenance
or create/run the dump/restore/A/B runner. Those remain separate review steps.

## Pilot-only minimum offline smoke CLI, not large benchmark

`rehearsal_smoke.py` wires three fixed tiny builds to the audited controller and
local backend: a printf success, deliberate exit17 and sleep120 cancelled by a
5-second supervisor timeout. It reads the same source/slice inventory first and
last and holds the private per-run lock. The exact source SHA must remain clean.
It requires an explicitly inventoried local shell-capable base image by full
image ID, with no unsafe ONBUILD/volume/custom shell behavior. No pull, setup,
SQL, restore, migration, large compilation or rollout occurs. No arbitrary RUN
body or Docker option can be supplied via inventory or CLI.

The Pilot must receive separate exact-SHA audit and execution approval before
running this command on the VM. This PR does not grant that approval. It will
write fixed per-case archives and a0600 smoke.json in an existing0700 output
directory. It refuses existing tags, case archives and receipts; use a dedicated
run inventory, not one whose identities are being reused concurrently.

```sh
python scripts/ops/rehearsal_smoke.py \
  --inventory /private-audit/run-inventory.json \
  --repo /isolated/exact-source \
  --base-image sha256:FULL_LOCAL_IMAGE_ID \
  --receipt /home/ubuntu/benchmarks/gerarai-6b2b/RUN_ID/serial/smoke.json
```

The hash and RUN_ID above are templates, not actual image/resource identities.
Only the Pilot chooses the existing local base and verifies its provenance.
A true success requires every RUN proof and final image check. Expected failure
or cancellation additionally requires a released real worker, terminal daemon
error, positive settled request and no live owned worker. The controller transports a typed reason, worker IDs alive at the requested
timeout and stopped-worker exit codes before cleanup. smoke-cancel requires
the timeout reason with an already released worker still alive at that deadline,
then confirmed cleanup. A generic cancel_request after daemon failure is not
proof of exercised live cancellation. smoke-failure requires daemon_failed and
exactly one nonzero stopped RUN exit code17, not sleep missing/exit127 or another
error. Missing, mixed or unconfirmed evidence fails closed. The CLI records
per-case progress and observed container IDs even when a case fails. An
interrupted/failed smoke receipt remains non-green. Keep the receipt private;
return a sanitized result summary with immutable residue IDs, not raw dumps.

Stopped owned containers/images are deliberately retained for ID-scoped cleanup
by the Pilot. Missing terminal acknowledgment or an unknown live worker needs
operator follow-up; no broad prune, name-prefix deletion or retry that hides
residue. All receipt authority flags stay false even after all three cases
pass. This only verifies the small exercise on that installed daemon at that
time; it does not approve the full A/B or establish duration-wide behavior of
large workloads. The smoke controller itself remains outside the shared slice,
so its host/API overhead is not claimed bounded or a measured concurrency gain.

The future dump/restore adapter will use trust only inside the isolated
loopback-only namespace, not passwords or production auth configuration. Source
must listen only127.0.0.1, with pg_hba local/127.0.0.1 trust, no other interfaces,
routes, ports or remote connections. A helper shares the validated full source
ID namespace without mounting its data volume, socket or .env. pg_dump+gzip
must use pipefail inside the common slice. Restore helper shares the DESTINATION
namespace, never the source's, and runs ON_ERROR_STOP=1 in a single transaction.
Private dumps remain0700 directories/0600 files on the VM and never enter
shared code/evidence artifacts. These DB operations are not implemented by this
smoke CLI and remain disabled pending the subsequent adapter review.
