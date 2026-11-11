# Complete TypeScript checking on a 2 GB machine

## Cause and scope

The original `npm run typecheck` and pre-push hook run a complete `tsc --noEmit` program. On the measured 2 GB machine with no swap, Node's automatic V8 heap limit is 997720064 bytes (about 951.5 MiB). The complete compiler needs more than that. The same input fails with heap exhaustion under the automatic limit and succeeds with a bounded 1408 MiB old-space limit.

This is not caused by the live-quote work queue. The base checkout is `4a28ed7f283cfe9db9a890416d7fb690b1686dec`, Node v22.23.4, TypeScript 5.9.3. Its broad `include` checks application code, scripts, unit tests and E2E together: 2242 root files and 4026 compiler source files in the final measured run. Parsing alone used about 604 MB of heap in an earlier diagnostic. Removing tests from the gate is not the fix.

`package.json` now invokes the local TypeScript binary through Node with `--max-old-space-size=1408`. The hook calls `npm run typecheck`, the same command CI already runs. No TypeScript include/exclude, strictness, library checking, diagnostic, incremental setting or dependency changes. No hook bypass. The previous `SKIP_TSC` behavior is unchanged, but is not used for validation.

The old-space limit is not a total-process RAM limit. Compiler objects, native allocations and other Node memory still count toward RSS. Running concurrent builds or other large jobs on the same 2 GB machine can still exhaust memory.

## Measured before / after

Same isolated machine, no production requests, same complete source scope. One run per row, not a statistical benchmark:

| Check | Result | Wall time | Maximum RSS |
| --- | --- | ---: | ---: |
| Original complete checker, automatic heap, cold (`--incremental false`) | SIGABRT / heap exhaustion | 17.19 s | 1070556 KiB |
| Complete checker, 1408 MiB heap, cold incremental cache removed | Exit 0 | 33.92 s | 1512332 KiB |
| Same command, warm incremental cache | Exit 0 | 4.89 s | Not separately measured |

The cold successful compiler reports 1389868 KiB of heap and 33.39 s compiler time. The warm compiler reports 769245 KiB and 4.37 s compiler time. Wall time includes npm/Node startup. The cold comparison is failure-to-success, not a claim that checking became faster than an unconstrained successful baseline.

## Alternatives tested

A four-project solution using `tsc -b` references (application, tests, scripts, E2E), all strict and no-emit, also fits. All original roots were checked, with ambient declarations included in each project. Cold: exit 0, 52.74 s, 1444060 KiB RSS. Warm: exit 0, 0.22 s in a subsequent run. Compared with the successful complete monolith, the extra configs and repeated dependency checking cost about 19 seconds cold and save only about 49 MiB peak RSS. These reference configs are not submitted.

An application-only diagnostic completes in 22.15 s, but excludes tests/scripts/E2E. It is not a valid complete gate and is not submitted. An 8 GB V8 heap on a 2 GB no-swap machine is not a useful remedy: it does not create RAM. No other environment is needed for this measured source tree. If future growth exceeds this machine, run the same unmodified complete gate on a machine with more RAM rather than omit checks.

## Validation and safeguards

- The command guard fails when the original automatic-heap command is restored.
- Real temporary `string`-to-`number` errors in `lib`, `tests`, `scripts` and `e2e` are all reported by the final complete command. It exits 2. Removing the probes returns exit 0, proving incremental invalidation does not hide errors.
- The pre-push behavioral test runs without `SKIP_TSC`, makes the typecheck command fail, and verifies the hook blocks the push.
- Scope guards retain `strict`, `noEmit`, incremental checking and the original root patterns/exclusions. Hook and CI use the same complete command.
- Seven focused Node tests and ESLint pass. No UI or financial calculation changes.

Reproduce: `npm ci`, then `npm run typecheck`. Delete the ignored `tsconfig.tsbuildinfo` first for a cold run. `npm run typecheck -- --extendedDiagnostics` prints compiler timings and heap use. Run `node --test scripts/typecheck-memory.test.mjs scripts/pre-push-hook-guard.test.ts` for the focused guards.
