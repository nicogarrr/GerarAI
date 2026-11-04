# Public market data, stage 1

This additive foundation is disabled by default. It creates four empty public
provider tables and an explicit read-only repository. No existing financial fact,
source document, thesis or portfolio row is promoted, copied, changed or deleted.
There are no new routes, network calls or production consumer changes.

## Boundary

- `public_source_documents`: issuer/listing identity, provider URL, checksum,
  retrieval timestamp and official flag. No arbitrary metadata or user identifiers.
- `public_financial_facts`: normalized metric/value/unit/period, filing date,
  XBRL concept, accession, confidence and namespaced derivation references.
- `public_financial_statements`: normalized numeric metrics only. A future trusted
  connector must validate the allowed fields before persistence.
- `public_analyst_targets`: provider, firm, publication date and TTL via its source.
- Existing companies, instrument references and market/benchmark prices are already
  global. Private documents, notes, keys, portfolio state, inferred inputs, models,
  valuation outputs, theses, audio and knowledge remain tenant-owned.

The repository only reads these public tables. It never bypasses tenant criteria
or searches private rows. It filters issuer, listing, currency, reporting period
and filing cutoff. Missing filing dates are excluded, not treated as historical
knowledge. The DTO uses `public:<id>` references, never ambiguous private fact IDs.
Absent debt stays absent. There is no financial calculation in this repository.

## Consumer contract

`metric`, Decimal `value`, `unit`, `period_end`, `filed`, `as_of`, `source_url`,
`source_checksum`, `fact_ref`, optional `accession`, `official`, `derived`, `concept`.

The calculation owner consumes facts and returns `ok`/`missing`/`conflict`, net debt
and component references. Debt/cash/investments must share closing date and unit.
No explicit debt fact means no zero debt. Cash-only net debt and full net debt must
be distinct, labelled outputs. WACC without proven capital structure is only cost
of equity. Terminal growth is a separate visible assumption.

## Later stages, not implemented here

1. Trusted SEC/ESEF/Yahoo/FMP ingestion validates identity, currency, provenance and
   provider field allowlists. It writes only freshly obtained public information.
   Do not convert tenant rows, accept raw metadata, store secrets, or infer consent
   from a source file. Provider terms and quota limits still apply.
2. A separately reviewed resolver combines public candidates with explicitly
   permitted private overrides from the current authenticated tenant. It preserves
   source priorities, coherent periods and reference namespaces. No cross-tenant
   read is required. Private-source reasons must not enter public caches.
3. Wire consumers behind the flag only after focused source-selection and private
   isolation tests. This foundation alone does not unblock PLTR for a new user.

## Release

Separate deployment lot. Require exact-SHA CI and independent final-tree review.
Before applying the migration, make a FULL backup and verify restore hashes.
Upgrade only creates the new empty tables and indexes; no data backfill. Deploy
with `PUBLIC_MARKET_DATA_ENABLED=false`. Activation and new-source loading need
separate reviewed steps with before/after read-only manifests. Preserve all Nico
rows. Downgrade drops only the new public tables; leave the flag off before using it.
