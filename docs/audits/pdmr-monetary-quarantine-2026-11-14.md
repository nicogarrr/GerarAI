# UK PDMR: unverified money is not an operational value

Five real tracefour rows were compared with the original FCA notices on
2026-11-14. In those five rows `totalValue` contains the original unit or
average price rather than the total transaction value. `pricePerShare` is
also inconsistent. Recomputing a total from those two fields cannot verify
it: the errors are correlated.

The recorded sample had 303 rows: five confirmed inconsistencies and 298
not checked against their original documents. This is not an error-rate
estimate. No other row is called incorrect just because it is unverified.
The five provider rows, original URLs and document excerpts are recorded in
`data-engine/tests/fixtures/pdmr_monetary_inconsistent.json`.

## Policy

- Retain every transaction and its shares, date, person and original link.
- Preserve provider price, value and currency in `data_quality` on ingestion.
- Set operational PDMR price/value to null until independently verified.
  This implementation has no verified bypass and infers no replacement.
- Apply the same policy at read time to legacy persisted rows. No production
  data migration or deletion is part of this patch.
- PDMR rows are not admitted into USD-only analytics, alerts or prose that
  labels the amount SEC/USD. They remain available in the feed and company
  summary. Timeline and alignment explain unverified amounts.
- Incomplete summary amounts, clusters and net flows are null, not false zero
  or a subtotal presented as a total. Missing counts are retained.
- Feed, company summary and saved filings display an ES/EN warning. Five
  confirmed rows have a stronger inconsistency warning; others say unverified.
  Client display guards also suppress stale cached PDMR monetary fields.

## Checks and limits

Five legacy rows are read through feed, saved filings, persisted fallback,
company summary, timeline, alignment and USD-only signal selectors. Reads
leave original stored values unchanged. Non-PDMR helper inputs are preserved,
including known zeros. No live database persistence claim is made.

Before the ingestion fix: five recorded mappings and their ingestion test
failed. Before client guards: two cached-raw/warning tests failed. Both pass
with the patch. The performance patch for cluster date parsing is integrated
separately from the monetary policy; its original microbenchmark evidence
is in `docs/performance/insider-clusters-2026-11-14.md`.

Visual checks use the real components rendered with controlled fixture data
and local CSS, in ES/EN at 390 and 1440 pixels. They are component previews,
not authenticated production screenshots. The before/after images retain
shares and filing links, remove the bad prices/totals and show readable
warnings without horizontal overflow.

## Reconciliación 2026-11-15 sobre main 43db2436

Se conservan las tablas/grid responsivas de #5663/#5665/#5667, el corte
independiente de publicación de #5673/#5679 y los importes desconocidos de
#5674. Conflicto de InsiderFeed resuelto manteniendo una sola tabla/fila:
normalizar PDMR antes del map y poner el aviso monetario en la celda importe.
No se recupera OperationCard ni el árbol móvil duplicado. Aviso con wrap en
móvil y ancho máximo en escritorio. Tests de warnings actualizados para
exigir una sola copia, no dos. Catálogo compacto regenerado.

Incluye el fix de cache previamente entregado: summary:pdmr-money-v2 y
supresión defensiva de agregados cacheados PDMR en InsidersSection.

132 pytest verdes con regresiones de publicación/unknown-money/PDMR,
95.55% combinado en quality/summary/ownership. 57 vitest verdes incluyendo
responsive tests; cache+summary frontend 100% líneas y 96.63% ramas.
check-i18n, guards completos, typecheck, ESLint, Ruff y diff-check verdes.

12 capturas inspeccionadas de componentes reales, fixtures estáticos ES/EN
390/1440: feed, summary y filings. Sin overflow horizontal; warnings legibles,
precios/importes PDMR ausentes y agregados cacheados suprimidos. Filings usa
un fallo parcial controlado en las señales para enseñar el estado persistido.
No prueba de hidratación, clics, producción ni suite VM/Browser E2E/Semgrep.
