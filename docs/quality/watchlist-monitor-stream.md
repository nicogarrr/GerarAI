# Watchlist monitor streaming

Controlled server test before/after (not browser LCP): basics and other sources
immediate; monitor unresolved. Base document did not resolve within 2500ms.
Changed page returns its element tree in11-12ms, imports excluded. Unresolved
basics still blocks, explicitly tested. No production latency attribution.

Monitor-only summary, rank, low52 badge and earnings cell have own Suspense.
Earnings placeholder keeps its table cell and aria-busy. Explicit metric sorts
retain their previous await and ordering, including earnings. Rejected entry
still does not receive monitor. Underlying action catches provider errors.

110 watchlist tests pass. Page source99.61%lines91.81%branches. Existing tests
that inspected synchronous earnings now resolve the actual monitor boundary;
all prior assertions retained. Unit node imports use local Vitest3.2.7, soCI
must check repository-lockfile versions. No full-build claim.

Visual evidence: actual monitor fragments rendered by SSR test in390px fixture,
not full Next app. Summary/rank/minimum/earnings visible. Translation keys are
intentional test mocks. Pilot full page and productionLCP remain outstanding.

## Auditor follow-up: waterfall guard

Guard now requires conditional monitor join for every metric sort, retains
synchronous parallel starts before basics, requires shared monitor stream and
checks earnings uses monitor date. Six source mutations must all be rejected:
serial monitor await, await between launches, metric monitor wait omitted,
earnings exempted from metricSort, stream promise replaced, earnings sort date
removed. Four waterfall guard tests pass, full guard runner3098pass/0fail/1skip
(3099tests),110watchlist tests still99.61%lines91.81%branches.
Local TS7 caused broad guard environment failures; local deps reset toTS5.9.3
and eslint/config-next installed, node_modules actual directory. No dependency
or lockfile edits included in this change.
