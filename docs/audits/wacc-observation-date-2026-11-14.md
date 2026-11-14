# WACC: preserve the observation date instead of inventing freshness

A controlled FRED response with `value=4.25` and no date previously saved
`risk_free_rate=0.0425` with today's date in both the financial fact and the
FRED source document. A malformed, impossible or future date was also saved
without validation. This is a reproduced persistence-path bug, not evidence
that the live provider returned such a response or that production has an
affected row.

The reader now requires a parseable observation date no later than the
refresh date. It skips ineligible dated rows and selects the next eligible
observation. If none exists, it creates no risk-free fact or FRED document.
A missing date is never replaced by retrieval time. Real dates remain in
both `FinancialFact.period` and document metadata, for API and CSV routes.
No numeric rate is corrected, no existing fact is deleted and no migration
or deployment is part of this patch.

Red first: eight tests failed before the fix: six missing/invalid/future
cases and two API/CSV fallbacks to a valid dated observation. Afterward,
71 WACC/connector/source-document tests pass. The changed service has
86.21% coverage including branches, with an explicit 85% test gate. Ruff
and diff checks pass. All provider data in these reproductions are test
fixtures. No model calls, paid services or production mutations were used.
