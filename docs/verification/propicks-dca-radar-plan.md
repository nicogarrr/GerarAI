# ProPicks + own DCA radar phase1

Authorized: single ProPicks expanded with DCA, larger universe, no new notifications, no production deploy. Ownership13F expansion remains out of scope.

## Capacity choice
Target1,000existing verified Company listings, not limited to tracked names or top20. Start persisted prices/qualified listings; display actual eligible/covered/excluded counts. Never invent1,000covered if data fails. No borrowing another user's private ProPickCandidate results: company market data can be shared, private tenant rankings remain scoped.

Local10-symbol benchmark (not VM):90,453dailybars,4.45swall,170.657mscombined engine computation,176MiBpeakprocessRSS,3,686,400bytesSQLitewithraw/adjustedclose. Several responses may be cached, small sample notSLA. Linear storage estimate1,000names~9Mrows/~369MBSQlitebeforePostgresindexes. Do not fetch max every day; seed5–10years and update incremental.1worker,1providerrequest/s cap, resumable1,000name daily budget and30min runtime ceiling, backoff/stop on429/challenge. VM snapshot measured below; sustained ingestion remains unmeasured.

## Market-data boundaries
- Own nico-v1 formula only. Monthly confirmed vs current forming kept separate.
- settled daily data from real listing, adjusted closes for signal, raw prices for levels and display, explicit currency/unit. No month low substituted for adjusted close.
- Price freshness and session check precede calculation. Contradictory same-session spot/history leaves invalid status, not4X.
- Current watchlist evaluator is NOT reused for persistence: it removes untracked symbols and can issue alerts. New shared market-data run/state, GET-only UI, explicit scheduled writer without outbox.
- At least24months for4X plus volatility/history constraints already in engine.

## UI
One ProPicks destination, opening main screener combines own DCA status + business quality. Mobile cards,20perpage, countsbyzoneandcoverage, filtersDCA/quality/FCF/sector/outsideheldortracked. Show confirmed monthly signal and provisional current month separately with price/session/source/formula version. Existing picks/quality/backtesting remain accessible in this one destination. No infinite scroll.

## Quality
Quality is separate from DCA zone. Reuse existing ProPicks gate evidence, but missing required leverage/FCF/input dates blocks "clear" designation. Proposed nonfinancial gates: coverage6/9,benefitspositive4/5with4yearsdata,ROIC/CFROI>WACC,leverage<3x,FCFpositiveandgrowingincomparableperiods. Sector-specific financial/REIT handling rather than wronggenericFCF. Proposed liquiditymedian20d dollarvolume>=5MUSD,cap>=1BUSD, explicit thresholds pending grounding to dataset.

## Implementation slices
A. Pure scan function +price-quality validation, benchmark,tests, no DB/network/alerts.
B. Shared marketdata persistence + bounded resumable worker/incremental refresh,GETpagedroute and coverage status, no LLM or notification path.
C. ProPicks composition mobile-first + tests/pixel inspection + regression.
D. Later explicitly approved phase2: newconfirmed4Xentries only, omittracked names, dedupe and daily digest.

## Tests
Lookahead/monthformation,insufficienthistory,stale/future/zero/mismatchedunit/mismatchedprice/splitadjustment,qualityN/Dnotpass,FCFperiodcomparability,liquiditymissing,sectorexclusions,stablepagination,tenantfiltering,noalertoutbox/noLLM,incrementalretry/budget429,resume,coverage>=85%,migrationroundtrip,390/1200pixelchecks.

## RDDT diagnostic
Liveproduction17:10noevaluatedDCAstate,quote91.61USD. Localyfinance2026-10-29history129.60USD,ownengine2Xforming/2XSeptemberconfirmed. Thirdpartypost93.17USD/4Xnotours. Conflictprevents"verifiedcurrentlevel".

## Production read-only capacity snapshot, 30 October 2026 16:17 UTC

- Host: 23,972 MiB total, 17,942 MiB available; root 193 GB, 45 GB free.
- Load 0.84, 0.73, 0.71; two current vmstat samples 70% and 99% CPU idle,
  1% and 0% I/O wait, no current swap-in/out in those samples.
- Shared PostgreSQL DB 5,148 MB; market_prices 108 MB, 229,311 rows,
  2,002 companies with prices. Company catalogue: 2,137.
- Last completed ProPicks run: 2,137 universe, 261 passed, 5,470 ms.
- Main worker uses 1.788 GiB of its own 3 GiB limit; PostgreSQL uses about
  785 MiB of its own 896 MiB limit. Host free RAM is not container headroom.
- This is a short read-only snapshot, not a sustained ingestion benchmark.
  No writes, service/config changes or full-history downloads were run there.

Recommendation: target 1,000 price-evaluated candidates first, selected from the
existing broader catalogue, not another 1,000 companies added blindly. Run one
bounded resumable history-ingestion worker, then incremental daily updates. Do
not preload 9 million ORM rows or batch all tickers in memory; process one ticker
at a time, commit/checkpoint each bounded batch and pause on provider throttling.
Keep the independent business-quality and price-validation gates explicit. Do
not publish a clear opportunity when the price conflicts (e.g. RDDT) or quality
is unavailable. No changes to existing container resource limits are authorized.

Remaining implementation: shared price/signal persistence and migration,
resumable worker integration with no alert side effects, tenant-aware read API
(excluding tracked names), one ProPicks UI with 20-row pages, mobile/desktop
visual QA, full affected tests and ready PR with instinct label. Current pure
core commit is scaffolding, not a finished user feature.


## Reference UI review and price-session correction (17:30 CET)

Reference screenshots suggest a useful information hierarchy, not a formula to
copy: counts by zone with coverage date, All / Recent Changes / Intramonth Close
Touches views, own "why" explanation, confirmed vs provisional side by side.
Recent Changes requires comparable persisted prior scans with the same formula
version. Missing history is pending, not zero. Intramonth touches must state they
use settled daily closes, not a real-time feed or intraday lows. No new alerts.

Live RDDT page at 17:30 explicitly separates current 30 October quote ~92 USD
from 29 October prior close 129.60 USD, showing -29.01%. The earlier comparison
91.61 vs 129.60 mixed sessions; it does NOT prove a same-session price conflict.
The previous "conflict" diagnosis is withdrawn. RDDT still has no evaluated DCA
state in production, and a third-party 4X is not our verified signal. The new
reference check correctly requires the same session and currency/unit.

Core now combines confirmed 4X + current settled-close 4X + independently
verified same-session price + full business-quality pass before a clear
opportunity flag can be true. Quality or reference missing never passes.
