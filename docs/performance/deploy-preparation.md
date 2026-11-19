# Deploy preparation: measurements before changing concurrency

This is opt-in tooling for the next reviewed preparation pipeline. It does not
change `scripts/deploy.sh`, CI, the Pilot's live scripts, production or any
resource limit. It does not contain SSH, Docker, migration, restore, deployment
or switch commands. Do not attach it to a live rollout without reviewing that
adapter and the exact command list separately.

## Measured baseline, 19 November 2026

Frozen cut `6b2b0e6c532dfc891b58cb84fac32d33b92bb3a5`. Source: Pilot's original
UTC phase files and command logs, converted to CET below. No timings in this
table are measurements made by the new tool.

| Block | CET interval | Measured seconds | What is included |
| --- | --- | ---: | --- |
| Preflight | 10:04:41 to 10:14:03 | 562 | Pyright 554 s wall (546.885 internal analysis), Ruff 3 s, setup |
| Backend | 10:14:03 to 11:03:19 | 2,956 | pytest 2,918.80 s, setup/evals; 30,437 passed, 69 skipped, 1 xfailed |
| Frontend | 11:03:19 to 11:54:59 | 3,100 | full npm checks; Vitest 2,159.19 s, 6,998 tests in 890 files |
| PG phase including manual gate | 11:54:59 to 11:59:08 | 249 | pytest 137.25 s, setup, about 90 s manual wait after 11:57:38 |
| Dump plus isolated restore | 11:59:08 to 13:00:56 | 3,708 | 188 tables verified, strict_restore=ok; dump/restore split unavailable |
| Backup end to build start | 13:00:56 to 13:01:21 | 25 | setup, not compilation |
| Builds | 13:01:21 to 13:13:38 | 737 | backend 103 s then frontend 634 s, based on exit-file times |
| Image source/migration check | 13:13:38 to 13:13:55 | 17 | source hashes plus isolated 0136 to 0138 twice |
| Green preparation to change | 13:13:55 to 13:16:10 | 135 | authorization/revalidation, not automatically wasted time |
| Live change to public switch | 13:16:10 to 13:19:53 | 223 | live migrations plus rollout, no exact split available |
| Live change through verification | 13:16:10 to 13:21:35 | 325 | includes switch, restart persistence, runtime/public/pixel verification |

Total frozen-cut preparation through verified close: 11,814 s (3 h 16 m 54 s).
The last two rows overlap: do not add them. Earlier failed/abandoned cuts are
not included. The live change itself is about 2.8% of total time.

## What this PR adds

`scripts/ops/deploy_preparation.py` has two separate modes:

- `time`: wrap one explicit, approved, synchronous preparation command. Record
  UTC start/end, monotonic command wall time, exact full SHA/tree and exit state.
  Refuse dirty tracked/untracked source, wrong SHA, receipt inside checkout and receipt reuse.
  Ignored build/cache/dependency files are outside Git's check, as are other
  mounts, images, services and data. This is not a content attestation for those.
  Recheck source after command completion; source drift cannot produce a passed
  receipt. Child stdout/stderr keep their existing routing. Receipts contain no
  command arguments, environment values or command output. Use an external
  private audit directory, not a source checkout.
- `plan`: simulate the ten fixed preparation phases from an explicit local JSON
  durations map. Default is serial. `overlap-build-backup` starts the build lane
  at the same simulated time as the dump/restore lane, after PG checks; backend
  and frontend builds remain sequential, then image migration verification.
  Maximum simulated concurrency is two phases. Both modes retain all ten items
  in the final barrier. It prints estimates only and never executes commands.

The tool has no rollout phase or automatic green-to-deploy hook. A successful
`time` receipt says only that the operator-supplied command exited zero on an
unchanged checkout. It does NOT certify that the command really ran the full
suite, restored a backup, checked a hash, used isolated services or built the
correct image. That is still the job of the reviewed command/adapter and Pilot.
This is not a security sandbox: an operator can supply any executable, so only
trusted, reviewed maintenance commands belong in `time`. Never read commands
from a PR body, log, remote JSON or other untrusted input.

## Operator use, only in a reviewed isolated rehearsal first

Requires Python 3.10 or newer and Git. No additional runtime package is needed.

Examples below are templates, not production instructions. Substitute real
reviewed paths, full SHA and timeouts; do not relax source checks to make them
pass. Commands must remain in the foreground until all their work has finished,
not launch detached children. Existing command output can contain secrets; keep
its normal protected log handling. The receipt does not copy it.

```sh
python scripts/ops/deploy_preparation.py time \
  --repo /isolated/exact-source --sha FULL_40_CHARACTER_SHA \
  --phase pyright --output /private-audit/pyright.json --timeout 1200 \
  -- bash /reviewed/pyright-complete.sh
```

The approved script must run the full unchanged check against that checkout,
not a different mutable mount. Keep npm installation and other setup inside the
corresponding complete phase and label it that way; do not call a full frontend
block "Vitest time". Use independent wrappers/receipts for the actual dump,
strict isolated restore, each image build and image migration check as their
phase boundaries allow. This wrapper doesn't
infer internal step timing; for finer splits, wrap the actual command inside
its approved script with the appropriate phase name. Never time an entire
compound script and label all its duration as Pyright, pytest or compilation.

Normal failure, launch failure, timeout, interrupt and source change have
non-passing receipt states. On timeout/interrupt, the wrapper terminates the
command's process group and reaps it, escalating to kill after five seconds.
An external SIGKILL or crash can leave a partial/running receipt. Neither is
passing evidence. Each retry gets a new receipt path; old evidence is retained.

Planning JSON must contain only numeric non-negative seconds for these keys:

```json
{
  "pyright": 1, "ruff": 1, "backend": 1, "frontend": 1, "pg": 1,
  "backup_dump": 1, "backup_restore": 1,
  "build_backend": 1, "build_front": 1, "migration_image": 1
}
```

These ones are a **synthetic format example**, not performance measurements.
Use complete phase wall times, not internal test-engine timing. The current
cut has no measured dump/restore split, so do not present a plan using an
invented partition as measured evidence.

```sh
python scripts/ops/deploy_preparation.py plan \
  --durations /private-audit/durations.json --mode overlap-build-backup
```

The plan reserves 600 seconds for final verification/change by default and
refuses reserves below 300 seconds. This is an estimate, not the operator's
actual release timing. Backup age is counted from simulated dump START through
planned readiness plus reserve, not from restore completion. At 7,200 seconds
or more it flags the backup outside the budget. The actual gate still checks
real dump age immediately before the change; refresh if necessary. Delays,
changed restore time and shared-resource contention can invalidate any plan.

## Proposed next rehearsal, not yet measured

After exact-SHA audit of this PR, adapt the Pilot's isolated preparation runner
in a separate reviewed change. Do not change production resource limits:

1. Record a serial baseline, including dump/restore split, npm setup, image
   build steps, CPU/RAM/disk pressure and application impact. Record the backup
   checksum, restore proof, source SHA and image digests outside timing receipts.
2. Rehearse only build/backup overlap on an isolated restored copy. Keep the
   same CPU/memory/IO budget. All suites, restore checks and image checks remain.
   Reject overlap if contention, errors or runtime impact outweigh the saving.
3. With the measured copy result, choose when to start the backup during the
   final suite phases. Keep enough freshness margin, or refresh rather than
   extending the 2-hour rule. A blanket backup at suite start can expire.
4. Pilot rollout still requires VM full suite green on exact SHA, fresh backup
   actually restored in isolation, exact same SHA front/back, all image/schema
   checks, explicit execution authority, and post-change verification.

Estimated upper bounds from this cut, **not additive or demonstrated savings**:
late backup/suite overlap up to 3,708 s; backend/frontend overlap up to 2,956 s
but highest resource risk; build/backup overlap up to 737 s; Pyright overlap up
to 554 s; PG technical work about 158 s. Local dependency/Next cache and delta
source-transfer savings remain unmeasured. The planner deliberately does not
enable suite parallelism, change cache keys or skip any command in this PR.

## Tests

`data-engine/tests/test_deploy_preparation.py` uses temporary synthetic Git
repositories and local child processes only. It covers exact SHA/clean source,
source drift, receipt reuse, command errors/signals/timeouts, process cleanup,
CLI, schedule dependencies, concurrency ceiling, invalid inputs and backup age.
No Docker, credentials, production, provider call or extra package is needed.
The test coverage config must include this script explicitly because scripts
are outside the backend product coverage paths. Measure the full script, not
only changed lines. This PR does not claim an actual build/backup speedup yet.
