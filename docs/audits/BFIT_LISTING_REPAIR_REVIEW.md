# Basic-Fit: identity and proposed repair review

Verified 2026-10-28:
- Euronext: BFIT, Basic-Fit, NL0011872650, XAMS. https://live.euronext.com/en/search_instruments/BFIT
- Yahoo: BFIT.AS, EUR. https://finance.yahoo.com/quote/BFIT.AS/key-statistics/
- Stooq: bfit.nl, XAMS BFIT, EUR. https://stooq.com/q/?s=bfit.nl

The pages returned historical April/May timestamps. They verify identity, NOT a current October price. Existing price-age gates remain unchanged. Stooq is an optional connector, not a newly enabled automatic fallback.

Code cause reproduced: Flex created/enriched a bare ticker with USD before recording its ISIN. This permits a US homonym lookup. No production record or original Flex payload was inspected, so the specific existing holding's history is unproven.

The fix resolves a reviewed ISIN before enrichment, creates BFIT.AS separately from an existing BFIT, and preserves both identities. Conflicting ISIN/currency is an explicit error. No fuzzy name fallback: a delisted US symbol alone does not prove an Amsterdam listing. Unknown issuers still need reviewed mappings. Other listings of the same ISIN must not be silently collapsed.

## Proposed correction, NOT authorized or executed

1. Read-only inventory: BFIT and BFIT.AS Company rows, their ISIN/exchange/currency, associated Positions and Transactions per tenant, original Flex raw_payload, MarketPrice currency/source/timestamp and any thesis or document references.
2. Prove the affected holding's ISIN NL0011872650 and EUR from its own Flex evidence. If missing or contradictory, stop for owner review. Do not use the bare ticker as proof.
3. Prepare an explicit plan listing row IDs, tenants, duplicate checks and rollback snapshot. If BFIT.AS already has a position or matching trades, reconcile duplicates manually before any reassignment.
4. Only with a separate owner order, in one transaction and with backup: reassign the proven position/transactions to the reviewed company, preserve native quantities/prices/currency and external IDs, isolate wrong-instrument prices rather than relabeling USD history as EUR. Reconcile dependent references and caches explicitly.
5. Verify tenant-scoped totals, unique operations, position values and dated EUR quotes. Never transform prices by changing a currency label.

No executable write script is supplied until the original records identify the exact safe operation. This PR does not migrate existing data, write production, enable a provider, or deploy.
