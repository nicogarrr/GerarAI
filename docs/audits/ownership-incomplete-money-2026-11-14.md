# Ownership evidence must not turn missing amounts into zero

Base c7f56d9. Controlled SQLite fixture, no production incident claim:
one insider buys1,000shares without price/value and another sells100at10.
The old reader emits buy_value0, net_value-1,000, 'Ventas netas de insiders',
and both thesis fact lines and markdown announce a complete monetary balance.

Fix:
- Count missing amounts per side. If any are missing, its total is null and
  the net balance is null. Keep trade/insider/share counts and known side.
- Keep real zero and shares-times-price fallback when both inputs are known.
- Keep count-based buying clusters, which do not claim a monetary balance.
- Emit N/D plus missing count in thesis prose and ES/EN panel lines. Never
  describe a partial subtotal as a full value. Unknown net alone is neutral;
  count-based clusters retain their existing positive tone.
- No persistence edits, inferred money, remote data or LLM execution.

Red-first2backend cases and1frontend case fail before. Green:24backend tests,
95.87% combined line/branch coverage of reader;36frontend tests,100%lines,
94.68%branches of formatter/types. Ruff/ESLint/typecheck/diffcheck green.

Visual evidence uses real OwnershipSignalsPanel and CSS, ES/EN390/1440,
controlled before/after payloads matching the reader reproduction. Panel body
is expanded for static capture by removing its hidden class and updating
aria-expanded; no hydration or click behavior validation is claimed. No
production screenshot or full VM-suite claim.

Overlaps publication cutoff f3083d8 and PDMR quarantine #5666 in the same
backend reader, but this patch is based on main only and does not incorporate
or undo either policy. Integrate and re-audit the final exact SHA.
