# Deep value: questionable data is visible, never scored

Base: 64b53515038d20a0c0aeb6b1c5b50b4ac3f0ebd5. Analysis and local patch only; no production mutation, LLM or push.

- Uses existing upstream rules, not an invented return cap: relative source disagreement >10% of the larger yield; extreme TTM yield >25%. These are review triggers, not a claim the value is impossible. A trustworthy 12% dividend keeps its full score.
- Entire affected row has score=null. Merely dropping the yield weight would still reward distorted book values. The API separates resultados and pendientes_revision, with an independent limit per section. Pending rows are alphabetical, not ranked.
- Pending rows keep raw values and both sources, but cannot satisfy the minimum-dividend screen. The UI also quarantines legacy flagged results during rolling deploys.
- A split factor alone does not prove a wrong P/B. Legacy non-unit factors without filed-aware basis metadata are unverified. New ingestion records shares period, filed date and adjustment method. No historical shares or price is manually changed.
- Where all arithmetic inputs exist, recomputes the trace formula only to check agreement within 1e-8 (the stored decimal precision), not to substitute a value. Source price dates, not generation dates, determine freshness.
- Structured special/liquidating/return-of-capital events are preserved and gated if supplied. Yahoo's current dividend list has no such classification; this patch does not fabricate it or hardcode a ticker.
- Positive P/B below 0.01 displays <0.01x, not 0.00x. No threshold declaring all small P/B false.

## Evidence and source corrections still needed

Production traces supplied by pilot show PARA TTM10.0 / close0.104 = 96.15384615; ELME TTM1.74 / close0.05 = 34.8. Those are persisted computations, NOT endorsed investible yields. No corrected yield is asserted.

PARA name/ticker alone is not proof of a Paramount collision. Banzai's own 8-K confirms PARA and a 1-for-10 reverse split starting 27 October2026. Reconcile CIK/issuer/listing temporal identity, split basis, filed facts and dividend-event issuer before asserting the cause:
https://www.sec.gov/Archives/edgar/data/1826011/000143774926033292/para20261016_8k.htm

ELME's emitter explicitly describes the1.74 payment as liquidating, with16.41 total2026 liquidation distributions. The stored TTM includes only1.74, not14.67 fromJanuary. A price after distributions cannot imply recurring return. Its2024 book value also predates liquidation:
https://ir.elmecommunities.com/press-releases/detail/382/elme-communities-provides-update-onliquidation-activities

The emitter confirms shares cancelled, trust interests non-transferable, dissolved6November. Company.delisted_at is NULL in the pilot evidence. Instrument lifecycle ingestion is a separate B2 fix; do not change account positions or master data in this patch:
https://ir.elmecommunities.com/press-releases/detail/384/elme-communities-transfers-remaining-assets-and-liabilities

## Verification

Red-first logs kept here. Backend85tests pass; deep_value97.63%, valuation_metrics94.08%, combined95.27% coverage including branches. Frontend15tests pass, DeepValueView95.55% lines94.87% branches. Full guards3072passed0failed1skipped. Typecheck, i18n7486keys, ESLint0errors, Ruff and git diff check pass. Not claiming entire backend/frontend suites.

Visuals render actual result-card components with clearly labelled QA fixtures at390/1440 ES/EN, inspected. Fixture EJEMPLO is illustrative, not a real pick. ELME/PARA raw metrics reproduce the observed production values. Before evidence is the production capture sent to parent. No live after/deployment claim.

Known migration consideration: API score becomes nullable and adds a pending section. UI uses optional pending section and handles old flagged arrays. Consumers outside this repository must adopt nullable scores. Review items do not consume valid result slots; total response can be2*limit, bounded200.
