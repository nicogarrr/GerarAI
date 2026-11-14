# Backend latency benchmark (advisory)

Depends on the clock-policy change (3b39afba9 or its equivalent): the guard
must honor PERF_GUARD_ENFORCE_WALL_TIME=1 and emit perf.warm_s/perf.cold_s.

The workflow `.github/workflows/backend-perf-benchmark.yml` runs only through
GitHub Actions **Run workflow** on a selected ref. No schedule, PR or push
trigger is added. No run is dispatched by this change. It does not spend
runner time until a person with permission starts it; check the repository's
included Actions quota before dispatching under the zero-spend constraint.

It uses a fresh hosted Ubuntu runner, Python 3.12, frozen dependencies and
one serial invocation of the existing performance-guard suite. No coverage,
xdist or other application suite runs alongside it in the job. This reduces
local contention but does not guarantee dedicated physical hardware or
prevent external hosted-runner noise. No production traffic or model calls.

The historical limits stay 2 s warm / 10 s cold. The measurement step fails
normally when a limit fails; pipefail preserves pytest's exit code through
tee. Job-level continue-on-error keeps this advisory. The summary reports
the actual measurement outcome, so a failed measurement is not called a pass.
It must not be selected as a required branch-protection check.

Evidence uploads under `backend-perf-<sha>-<attempt>`, retained 14 days:
- `pytest.log`: assertions, durations and exit diagnostics.
- `junit.xml`: per-case measured wall-time properties (when pytest starts).
- `environment.txt`: SHA/run ID, date, CPU, RAM, OS, load and disk.
- `environment-after.txt`: date, load and RAM after measurement.

Environment capture precedes dependency installation. Evidence upload and
summary run with always(), including a failed measurement/setup. JUnit/log
cannot exist when setup fails before pytest starts; the environment files
and step outcomes distinguish that case. Cancelling the job or a hard
runner failure can still prevent artifact upload.

Validation: red first on missing workflow; five static workflow/concurrency
tests green. Pins copied from existing CI. YAML parsed, command options
checked against the locally executed controlled benchmark in the preceding
change. No Actions execution, runner result, remote publication or PAT scope
is claimed. The patch/bundle is handed off for publication and exact-SHA QA.
