/**
 * Etiquetas de los fundamentales TTM en la ficha. Ejecución:
 *   node --experimental-strip-types --test scripts/ttm-display.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { isoDateEs, ttmHasData, ttmPanelMetrics, ttmPeriodText, ttmQuartersText } from '../lib/research/ttm-display.ts';

// Ventas de Apple a 27/06/2026: Q4 FY25 inferido (FY − 9M) + Q1-Q3 FY26 de los 10-Q.
const revenue = {
  metric: 'revenue',
  value: '466823',
  unit: 'USD',
  basis: 'TTM' as const,
  label: 'TTM (últimos 4 trimestres)',
  provenance: 'INFERIDO' as const,
  period_end: '2026-06-27',
  quarters: [
    { period_end: '2025-09-27', value: '102466', reported: false, origin: 'FY-9M' },
    { period_end: '2025-12-27', value: '143756', reported: true, origin: '10-Q' },
    { period_end: '2026-03-28', value: '111184', reported: true, origin: '10-Q' },
    { period_end: '2026-06-27', value: '109417', reported: true, origin: '10-Q' },
  ],
};

describe('TTM en la ficha', () => {
  it('fecha ISO a dd/mm/aaaa sin husos horarios', () => {
    assert.equal(isoDateEs('2026-06-27'), '27/06/2026');
    assert.equal(isoDateEs(null), null);
    assert.equal(isoDateEs('basura'), null);
  });

  it('la línea de periodo dice TTM y hasta cuándo; el FY dice su cierre', () => {
    assert.equal(ttmPeriodText(revenue), 'TTM (últimos 4 trimestres) · hasta 27/06/2026');
    assert.equal(ttmPeriodText({ basis: 'FY', period_end: '2025-09-27' }), 'FY (último ejercicio) · cierre 27/09/2025');
    assert.equal(ttmPeriodText({ basis: 'Q', period_end: '2026-06-27' }), 'Último trimestre · cierre 27/06/2026');
    assert.equal(ttmPeriodText({ basis: 'SIN_DATOS', period_end: null }), 'Sin datos');
  });

  it('el desglose marca el Q4 derivado como inferido', () => {
    assert.equal(
      ttmQuartersText(revenue.quarters),
      '27/09/2025 (Q4 = FY − 9 meses, inferido) + 27/12/2025 + 28/03/2026 + 27/06/2026',
    );
    assert.equal(
      ttmQuartersText([{ period_end: '2026-06-27', value: '1', reported: false, origin: 'YTD' }]),
      '27/06/2026 (acumulado restado, inferido)',
    );
    assert.equal(ttmQuartersText([]), null);
  });

  it('sin datos no se enseña el panel; con una métrica sí', () => {
    assert.equal(ttmHasData(null), false);
    const empty = { ticker: 'X', as_of: null, formula: '', metrics: [{ ...revenue, value: null, basis: 'SIN_DATOS' as const }] };
    assert.equal(ttmHasData(empty), false);
    const full = { ticker: 'AAPL', as_of: '2026-06-27', formula: '', metrics: [revenue] };
    assert.equal(ttmHasData(full), true);
    assert.deepEqual(ttmPanelMetrics(full).map((m) => m.metric), ['revenue']);
  });
});
