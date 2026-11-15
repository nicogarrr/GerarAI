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

## i18n rejection follow-up

The original patch exceeded the hardcoded Spanish literal ceiling (30 vs 29).
Moved missing-amount text and the unknown-net reading into ownership dictionary
keys in ES/EN and regenerated en.compact.json. No baseline increase. Relative
.ts import preserves the existing standalone node guard contract.

check-i18n passes. Full guards: 3063 passed, 0 failed, 1 skipped.
36 formatter/panel tests pass, 100% lines and 94.68% branches. Typecheck and
ESLint pass. This changes text storage, not rendered text or amount semantics.

## Semgrep count-default follow-up

`value_missing` is a count, not money. Replaced its `or 0` default with an
explicit `None` check and named it `missing_count`. No suppression or rule
change. Added four regressions for None/0/1/3, preserving N/D monetary values.
43 ownership pytest pass; reader coverage 95.95% combined. check-i18n and
full guards pass (3063 passed, 0 failed, 1 skipped). Semgrep is not installed
locally, so its exact CI rerun remains required; the matching pattern is gone.

## Reconciliación con main afceca89, 2026-11-15

Se conserva el corte de publicación de #5673 y el guard de importes ausentes.
El único conflicto del rebase fue en en.compact.json, resuelto regenerándolo
desde los diccionarios. No se cambia el contenido de insider_feed,
insider_summary, InsiderFeed ni los avisos/PDMR existentes en main; #5666
sigue fuera de esta rama y no se atribuyen sus futuros cambios a este parche.

Prueba de composición rojo/verde: la misma pareja de casos falla por importe
cero falso en main sin #5674, y por aceptar publicación futura en #5674 viejo
sin #5673. Tras componer, publicación pasada + importe ausente da N/D; el
mismo importe ausente en filing futuro no contamina el saldo conocido actual.

54 pytest verdes incluidos los nueve casos de corte de publicación de #5673;
reader 96.04% combinado. 36 vitest, 100% líneas/94.68% ramas; typecheck,
ESLint, Ruff, check-i18n y guards completos (3066 pasan/0 fallos/1 omitido).
No suite completa, Browser E2E ni Semgrep local. Sin push/merge/despliegue.
