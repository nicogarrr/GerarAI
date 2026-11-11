# Management alignment: recorded filings and conservative plan attribution

This follow-up uses the existing recorded bytes, without downloads, new services or paid data. No thesis, valuation, DCA or legacy insider signal is changed.

## Recorded evidence

- `tests/fixtures/sec_debt/unh.json.gz`, `pltr.json.gz`, `chtr.json.gz`: original companyfacts corpus. Tests verify decompressed length and SHA256 against each existing `.source.json` manifest before using it. The manifest records the retrieval date and source URL. These are recorded historical snapshots, not current live assertions.
- UNH and PLTR exercise reported closing shares. CHTR exercises the weighted diluted fallback. All three exercise SBC, repurchases, revenue and annual comparative shares repeated in later annual filings. Expected 2024 and 2025 share amounts and computed percentages are pinned independently in tests.
- `tests/fixtures/form4/meta_0000950103-26-016314.xml`: existing recorded META XML. It contains a root checkbox plus transaction-specific coding reference F1. F1 says: "The sale reported was effected pursuant to a Rule 10b5-1 trading plan adopted by the reporting person on November 25, 2025." The note has exactly one document reference. The test pins the existing repository fixture to 3835 bytes and SHA256 `8b64b5f299d01ca9583247075096a4486ff4b6e54a1457aef749fb0f7b52ef79`. This is an integrity check against the repository base, not independent download provenance; no original source manifest is claimed.

The companyfacts ingestion test replaces the SEC client with those bytes and builds an offline annual-anchor contract from their annual-duration entries. That anchor map is NOT an independent recorded submissions payload. Instance/extension/free-data calls are disabled. This proves the normalizer, persistence and aggregation with recorded financial facts, not a live external ingestion or independent submissions check.

## Attributing the root checkbox safely

A root checkbox alone never classifies any transaction. Root false never means every transaction is outside a plan. A transaction-level explicit checkbox remains the first choice.

A root true/1 can support a planned sale only when all of these hold:

1. The transaction code is S.
2. Its own `transactionCoding/footnoteId` points to the affirmative note.
3. That note ID is referenced exactly once across the entire filing, including nonDerivativeHolding and derivativeHolding fields. Shared or multiply referenced notes are not allocated.
4. The note matches the deliberately narrow affirmative sentence above, including an adoption-date clause. Generic plan mentions, conditional language, negations and notes about holdings do not qualify.

The root is corroborating document evidence. The unique transaction coding reference and affirmative sentence supply attribution. Other transactions remain unknown even in that same document. No natural-language model is used, no document-wide flag is copied across rows, and legacy `rule_10b5_1` is unchanged. The derived explicit flag is persisted through the existing nullable enrichment path.

This does not claim full Form 4 coverage. Other valid issuer phrasing or ambiguous multi-transaction notes still return unknown. In particular, missing/no checkbox plus no attributable evidence is unknown, never false. The existing pre-2023 synthetic tests continue to check that contract.

## Controlled interventions, not real events

Tests remove references, remove marks, negate/change notes, add an unmarked second transaction, share a note, or change the transaction code using copies of the recorded META XML. These are explicitly controlled test variants, not claimed real filings.

Similarly, ticker_change, split and reverse_split events are injected against the real persisted financial balances. They prove that an unrelated corporate action does not hide a real percentage, while both split types prevent an unadjusted comparison. They are NOT assertions that UNH, PLTR or CHTR underwent those actions at the test date. No claim is made that a recorded ticker-change filing or recorded split filing was added.

The earlier phase-1 limitation about root-level META remaining unknown is superseded only for the uniquely attributable F1 case. All root-only or ambiguous variants remain unknown.
