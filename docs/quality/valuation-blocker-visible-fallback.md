# Unknown valuation blocker remains visible

Base main ac7490c7. Red regression first73d565c, implementation7df4c37.
Checked actual backend long_term_model_service._scenario_payload: it emits
forecast_missing,current_net_debt_missing,terminal_shares_missing,
wacc_not_above_terminal_growth,terminal_fcf_not_positive. All retain their
existing translations. No model calculations or machine tokens change.

Object.hasOwn prevents constructor/toString/__proto__ from resolving inherited
Object properties as translation keys. For a missing valuation with unknown
blockers, a nonempty backend note still wins; if absent/blank, display the
translated known labels plus raw unknown tokens. Unknown text is not guessed
or reclassified. Existing header keys remain limited to known translations.

Run: npx vitest run --config scripts/vitest-valuation-blockers.config.mts --coverage
and node --experimental-strip-types scripts/valuation-blockers-guard.test.ts.
4unit tests andexistingnode guard pass; full source100%lines/branches.
Focused strict TypeScript passed on changed sources/tests and imports.
Local Vitest3.2.7/Node22.23.4; lockfile CI still required. No full UI build,
rendered component validation, production, merge or deployment claim.
