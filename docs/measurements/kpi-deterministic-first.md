# KPI extraction: deterministic first, candidates only

## Processing modes

`KPI_EXTRACTION_MODE=auto` is the default. The deterministic parser runs
before Jev, provider creation, call quota or LLM budget reservation. Only
registry metric keys with no deterministic candidate go to the existing
bounded LLM fallback. A candidate for one period covers that metric key
for this pass; this is NOT a claim that all historical periods are complete.

`KPI_EXTRACTION_MODE=deterministic-only` on worker-kpis permits a zero-LLM
pass of queued extract_document_kpis jobs. It neither creates a provider
nor invokes Jev, reserves call quota, checks LLM budget or calls complete.
It does not change LLM_FREE_ONLY. Other actor types on the same queue are
NOT made deterministic by this knob. Deployment and queue changes need
their own operational gate; nothing is executed against production here.

Unresolved keys remain in document metadata `kpi_deterministic` with mode,
parser version and candidate counts. Actor returns partial if this mode
leaves keys unresolved, not a claim that the document's KPIs are finished.
The kpi_deferred queue-admission marker is removed after this pass, as in
the existing actor; the unresolved list is retained for review/requeue.
A later auto pass may request LLM for the unresolved metric keys. Existing
legacy LLM candidates retain their original idempotency behavior.

Deterministic candidates commit before fallback when commit=True, so a
failed LLM does not discard free results. commit=False keeps the caller's
transaction semantics. Candidate creation never creates FinancialFact.
All candidates still require review/approval with the exact stored chunk
quote. No normalization/grounding gate is bypassed. In particular, units
in a table header or XBRL scale attributes may produce needs_review rather
than pending_approval under the existing quote-grounding rules.

## Supported strict formats

- SEC and IR: an entire row of exact registered KPI alias, explicit FY/Q
  period, explicit canonical-compatible currency/unit, and a single number,
  separated by pipes, tabs or colons. Example:
  `Revenue | FY2025 | USD million | 123.4`.
- SEC only: complete XML inline-XBRL fragment with standard namespace-bound
  us-gaap concept allowlist, same CIK, unsegmented annual duration context,
  explicit DocumentFiscalYearFocus and supported currency/scale. No inferred
  fiscal year, guessed quarter, YTD-to-quarter conversion, extension concept
  mapping, ambiguous transform, dimension aggregation or currency inference.
- IR realized gross-margin percentages with an explicit current-quarter
  declaration in the same or immediately preceding chunk. Store the exact
  result sentence AND the exact reporting-period declaration as two source
  locators, both verified against persisted chunks. Guidance/prior-period
  sentences, scripts/JSON and mixed quarter declarations are rejected.
- SEC/IR simple monetary result sentences require exact registered label,
  explicit FY/Q period and ISO currency in that sentence. Revenue/net-income
  type labels are not extracted unless present in that company's registry.
  Bare `$` is not resolved from the ticker or market, and CAD is not relabeled
  USD. This broader rule produces no additional candidates in the sample.
- Unknown labels/units/periods and ambiguous narrative are left unresolved.
  Contradictory parsed rows for the same key/period remain needs_review.
- Deterministic retrieval scans up to500 persisted chunks, not just the
  first30. Fallback LLM retrieval remains first30 chunks/max30000 characters;
  this PR does not claim to solve noisy native_html extraction or retrieval.

## Real backlog dry-run

Pilot export as of 2026-11-12T08:57:33.773128+00:00:
489 pending extract_document_kpis jobs,489 distinct documents, all IR,0 SEC.
All489 have chunks. A systematic sample of30 sorted document IDs at indices
floor(i*488/29), i=0..29, includes endpoints. The sample has no inline-XBRL
nonFraction/context/unit markup and uses native_html parsing. Its sources
are BN and KRKNF; it is not a random sample of all possible company filings.

Measured with scripts/measure_kpi_deterministic.py, read-only on the export:

| Measure | Result |
| --- | ---: |
| Sample documents | 30 |
| Active document+registry-key opportunities | 322 |
| Opportunities with deterministic candidates | 2 |
| Deterministic coverage of expected registry keys | 0.6211% |
| Documents with any deterministic candidate | 2/30 (6.67%) |
| Chunks scanned | 1716 |
| Documents truncated at the500-chunk bound | 0 |

This is candidate coverage, not accuracy, approval or coverage of every
claim actually present in the source. Missing registry metrics count in
the denominator even when a particular release does not report them.
No claim is made that0.6211% is the exact percentage for the entire489 or that
these documents contain no useful data. This parser does NOT solve the
current backlog: a zero-LLM pass records unresolved work rather than
inventing values. XBRL support helps future SEC documents, not this IR set.

Observed failure modes: index/press-release navigation, CSS/JSON-LD before
the body, narrative figures with `$` but no unambiguous currency/period,
and sector KPI names not matching a supported explicit table. Some result
bodies appear around chunk66-70, beyond the existing LLM first30 retrieval.
The parser does not infer USD from `$` or a company's registry default.
The measured KRKNF releases explicitly say Canadian dollars; registry USD
therefore does not justify money candidates in USD.

Reproduce from data-engine with the authorized export path:
`python -m scripts.measure_kpi_deterministic EXPORT.json.gz`.
The export is private and is not committed; this report contains aggregate
counts only. No user/account identifiers, source bodies or credentials.

## Iterations and reserved validation

Before the improved prose rules, explicit-row/XBRL-only baseline was
0/322 (0%). For further work,20 documents (215 opportunities) were used for
development and10 (107 opportunities) reserved. The reserved zero-based
indices were2,5,8,11,16,17,20,23,26,29. Metadata and some diagnostic snippets
from all30 had already been seen before this split, so this is NOT a fully
blind holdout. No further reserved body inspection or tuning against its
outcomes was used. One initially proposed reserved index14 was moved to
development because its body had already been explicitly inspected, and
index16 replaced it before reserved outcomes were measured.

| Stage | Development opportunities | Reserved opportunities |
| --- | ---: | ---: |
| Strict row/XBRL baseline | 0/215 (0%) | not used for tuning |
| IR same-chunk quarter/result rule | 1/215 (0.4651%) | not inspected |
| Adjacent quarter-context support alone | 1/215 (0.4651%) | not inspected |
| Sentence-level result, rejecting only guidance sentence | 2/215 (0.9302%) | 0/107 (0%) |
| Explicit period+ISO-currency result sentence | 2/215 (0.9302%) | 0/107 (0%) |

Two sampled candidates were manually checked against their result and
period quotes: gross margin Q1 2025 is62.7% (not the comparative44.8%) and
Q3 2025 is59% (not the comparative52%). Both are correctly represented as
decimal rates0.627 and0.59. This is2/2 manually supported candidates in the
development set, NOT an unbiased100% precision estimate. Reserved validation
emitted no candidates, so its precision is undefined. All remain unapproved
candidates; no live candidate or fact was written during this dry-run.
