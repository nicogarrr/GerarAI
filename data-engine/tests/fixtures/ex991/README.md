# Earnings-exhibit corpus

Original SEC HTML downloaded 2026-11-04, compressed reproducibly. `sources.json`
pins URL, decompressed SHA256 and byte length. All eight sources are SEC exhibit
URLs. No synthetic figures replace the statements. Test figures use the precise
GAAP tables, not rounded narrative or adjusted/non-GAAP summaries.

Accepted examples: UBER, CHTR, MSFT, ASTS, PLTR. Thousands and millions retain their
original `value` and `scale`: base-currency amount = value * scale. Capex retains
the cash-flow sign (normally negative). Consolidated and attributable earnings
are different metrics. D&A comes only from the CF reconciliation; "D&A and other"
is deliberately not plain D&A. Cash equivalents never silently include securities.

UNH and TSLA contain images/hidden text but zero HTML tables. JPM's narrative
exhibit lacks recognized statement tables. These are rejection fixtures, not
successful extraction claims. No OCR is performed. A fifth quarterly column in
an image is not treated as a parsed column.

API: `parse_ex991_tables(markup, source_url=..., published=...,
reporting_currency=...)` requires independently verified currency. A dollar sign
is not enough. `select_ex991_fact` returns an exact requested period or N/D plus
the latest available period end. It never constructs Q3 from Q2/YTD or annualizes.
`published` is the caller-supplied actual publication date, not retrieval date.

Limits: explicit English month/day headers, calendar quarter/year durations,
recognized statement labels, dollar-denominated currencies, thousand/million
scales. One displayed-unit rounding tolerance per equation. Unsupported forms,
missing equations and failed arithmetic reject the entire table-period. A
conflicting duplicate metric/period rejects all facts for the exhibit. Caller
owns issuer identity, Item 2.02/exhibit provenance and later 10-Q replacement.
No network, database changes or product wiring is part of this module.
