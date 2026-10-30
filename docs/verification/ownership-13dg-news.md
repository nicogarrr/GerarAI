# 13D/G declarations in Seguimiento and Noticias

- Read-only panel uses saved filings, never starts a scan.
- Separate reporting group, snapshot date and filing date.13G is not13F and not a trade.
- Existing SEC poll and structured monitor share one non-alerting writer.
- Identity is tenant+accession with a database unique constraint; alternate XML/XSL paths adopt the same SEC event. Amendments remain separate.
- Existing SEC news rows are adopted by canonical accession. Other publishers remain independent coverage.
- Materiality6/10 is an explicit editorial rule for regulatory ownership disclosures, neutral direction, not an SEC measurement. It does not imply a purchase or issue alerts/ThesisChange.
- Migration0104 adds a nullable unique identity column. No historical rows are deleted or silently merged. Requires verified backup and a separately authorized backend deployment.
- Existing saved filings appear in the panel; news enrichment occurs when a producer processes the filing. No production sync or backfill was run.

## Verification
-71targetedpytestpassed, including both publisher orders, amendments,tenant separation,legacy adoption,invalid source/issuer/date,no new alerts,immutable verified values,uniqueness enforcement and migration upgrade/downgrade preserving existing rows.
- Backend writer/persistence coverage94.12%;frontend panel/format helpers100%lines/branches.
-6Vitestpassed. TypeScript4GBpassed.2641repositoryguards passed. Ruff on changed Python and ESLint on new TS passed.
- Actual component rendered with real SEC fixture and appCSS at390px/1200px, inspected pixels. Local fixture preview, not deployed app.
- Full pytest collection succeeds after local test dependencies installed, but entire14k+suite did not finish inside the bounded local run. Do not call the full suite green; CI must finish before merge/deploy.
- SEC primary Vanguard fixture: https://www.sec.gov/Archives/edgar/data/1780312/000210011926001548/primary_doc.xml .15,330,194shares,5.11%,snapshot2026-09-30.
