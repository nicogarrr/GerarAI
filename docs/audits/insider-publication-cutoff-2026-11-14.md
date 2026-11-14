# Insider readers: publication cutoff

Base: c7f56d9 (#5644 already prevents unpublished filings in company summary).

A controlled SQLite reproduction persists a filing dated tomorrow with a
transaction dated yesterday. Before this patch, feed, followed-company
operations and ownership/thesis evidence all count its value as current
activity. Three new regression cases fail before the fix; six controls
(published today or publication date missing) pass.

Publication and transaction dates are independent eligibility gates. This
patch rejects a future publication date even when the transaction is in the
requested window. Feed and operations reuse their existing excluded_future_rows
counter, counting each rejected row once. Ownership returns its existing
sin_datos response when no eligible operations remain. No stored data is
changed. Unknown publication dates preserve the existing fallback behavior;
this is not proof that an unknown publication date was valid or current.

Tests use real service readers with an in-memory database. This demonstrates
the code path, not a claim that future-dated filings exist in production.
No remote ingestion, LLM calls, account operation or production deployment.

Focused regression suite: 62 passing across the three touched service areas,
94.40% combined line/branch coverage (feed94.16%, operations97.48%,
ownership92.16%). Ruff and git diff --check pass. No full VM suite claim.
