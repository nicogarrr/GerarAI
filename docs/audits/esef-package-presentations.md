# Issuer-package presentation safety

The package builder previously fed oldest-first reports into a first-wins
merge. A later comparative presentation could disappear. Simply reversing
that order would still combine facts from different accounting perimeters.
For example, Kerry's original FY2023 revenue includes Dairy Ireland while
the FY2024 filing presents FY2023 continuing operations after the disposal.
Neither chronology nor matching concept/unit/period proves equivalence.

## New issuer-package contract

- `facts` keeps its existing normalized shape, but contains only facts from
  the latest accepted package. No older-package fallback for missing concepts
  or years. Selection means latest presentation, not a claim of universal
  accounting correctness or cross-period comparability.
- `presentation_archive` preserves each original report's full parsed facts,
  filing period, source URL, SHA256 and report path. It is an archive, never
  a merged series. Existing consumers read only `facts`.
- `selected_presentation`, `presentation_policy`, and `coverage` expose the
  selection, older-only fact-key count, and absence of asserted comparability.
- Multi-package output sets `requires_presentation_review`. The actual
  `refresh_from_esef` entry point refuses it BEFORE source creation/deletion
  or commit. This prevents the existing replace-all ingestion operation from
  deleting historical facts or unrelated metrics merely because they are
  missing in the selected report. Existing snapshots without this flag retain
  their existing behavior. The filing-index lane is unchanged.

## Deliberate limitation

This is containment, not an automatic historical accounting migration. A
single current presentation usually offers fewer years than all packages.
The synthetic regression quantifies one excluded older-only concept and
retains both original 8,020.3m and re-presented 6,974.9m amounts in separate
archives, with only 6,974.9m selected. Production coverage has not been measured.
The builder does not silently discard archives or claim scope continuity.
Future ingestion of these multi-package snapshots needs an explicit reviewed
presentation/scope migration policy, not merely removing the guard or doing a
blanket latest-wins backfill. No current snapshot, database, or history is
rewritten by this PR.

Issuer evidence supplied with the reproducible audit:
- https://www.kerry.com/content/dam/kerry/docs/annual-report-2023/esef-tagged.zip
- https://www.kerry.com/content/dam/kerry/en/pdf/investors/results-presentations/2025/635400TLVVBNXLFHWC59-2024-12-31-en.zip
- https://www.kerry.com/content/dam/kerry/en/pdf/investors/results-presentations/2025/kerry-preliminary-results-2024-press-release.pdf
