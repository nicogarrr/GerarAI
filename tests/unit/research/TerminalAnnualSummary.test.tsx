import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FinancialTerminalSection, type FinancialTerminalData } from '@/components/research/sections/FinancialTerminalSection';
import { annualSummary, fiscalYear } from '@/lib/research/terminal-summary';

// Nico, 8-nov-2026 (AITerminal, «comparar 10 años de métricas»): dentro del
// Terminal que ya existe en Finanzas, sin pestaña nueva. Ingresos reales de
// POOL (10-K, SEC): 2.363,1 M$ en 2015 y 5.289,4 M$ en 2025.
const pool = [
      { id: 1, period: '2015-12-31:FY', value: 2363139000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 2, period: '2016-12-31:FY', value: 2570803000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 3, period: '2017-12-31:FY', value: 2788188000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 4, period: '2018-12-31:FY', value: 2998097000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 5, period: '2019-12-31:FY', value: 3199517000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 6, period: '2020-12-31:FY', value: 3936623000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 7, period: '2021-12-31:FY', value: 5295584000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 8, period: '2022-12-31:FY', value: 6179727000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 9, period: '2023-12-31:FY', value: 5541595000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 10, period: '2024-12-31:FY', value: 5310953000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
      { id: 11, period: '2025-12-31:FY', value: 5289396000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 1, source: { title: '10-K', type: 'sec' } },
];

const pt = (period: string, value: number | null, extra: Record<string, unknown> = {}) => ({ period, value, unit: 'USD', status: 'reported', segment: 'consolidated', ...extra });

describe('annualSummary (Terminal)', () => {
  it('TACC, media, mínimo y máximo de los ejercicios cargados', () => {
    const s = annualSummary(pool)!;
    expect(s.years).toBe(11);
    expect([s.firstYear, s.lastYear]).toEqual([2015, 2025]);
    // (5.289.396 / 2.363.139)^(1/10) − 1 = 8,39 %
    expect(s.cagr).toBeCloseTo(8.39, 2);
    expect(s.min).toEqual({ year: 2015, value: 2363139000 });
    expect(s.max).toEqual({ year: 2022, value: 6179727000 });
    expect(s.mean).toBeCloseTo(rev().reduce((a, b) => a + b, 0) / 11, 0);
  });

  it('solo ejercicios anuales consolidados, una cifra por año y la reportada manda', () => {
    const s = annualSummary([
      pt('2024-12-31:FY', 100), pt('2024-12-31:FY', 999, { status: 'calculated' }), pt('2025-06-30:Q2', 5000),
      pt('FY2025', 121), pt('2025-12-31:FY', 777, { segment: 'Europe' }), pt('unknown', null), pt('2026-11-08', 1),
    ])!;
    expect([s.years, s.firstYear, s.lastYear]).toEqual([2, 2024, 2025]);
    expect(s.cagr).toBeCloseTo(21, 6);
    expect(fiscalYear('2025-06-30:Q2')).toBeNull();
  });

  it('sin TACC para ratios ni cuando el primer o el último ejercicio es ≤ 0', () => {
    expect(annualSummary([pt('FY2020', 0.2, { unit: 'decimal' }), pt('FY2025', 0.3, { unit: 'decimal' })])!.cagrReason).toBe('ratio');
    const loss = annualSummary([pt('FY2020', -5), pt('FY2025', 10)])!;
    expect([loss.cagr, loss.cagrReason]).toEqual([null, 'sign']);
    expect(annualSummary([pt('FY2025', 10)])!.cagrReason).toBe('single_year');
    expect(annualSummary([])).toBeNull();
  });

  it('nunca mezcla monedas: se queda con la unidad del último ejercicio', () => {
    const s = annualSummary([pt('FY2020', 50, { unit: 'EUR' }), pt('FY2021', 100), pt('FY2023', 121)])!;
    expect([s.years, s.firstYear, s.unit]).toEqual([2, 2021, 'USD']);
    expect(s.cagr).toBeCloseTo(10, 6);
  });
});

describe('Terminal financiero con resumen de 10 años', () => {
  it('muestra la TACC, la media y el rango encima de la serie', () => {
    const terminal = {
      coverage: { percent: 100, available: 1, requested: 1 }, periodicity: 'annual',
      metrics: [{ metric: 'revenue', status: 'available', definition: 'Reported consolidated or segment revenue.', canonical_formula: null, periods: 11, segments: ['consolidated'], missing_reason: null, series: pool }],
    } as unknown as FinancialTerminalData;
    render(<FinancialTerminalSection locale="es" periodicity="annual" terminal={terminal} years={11} />);
    const line = screen.getByTestId('terminal-annual-summary');
    expect(line).toHaveTextContent('TACC 2015–2025: +8,4 % al año');
    expect(line).toHaveTextContent('11 ejercicios (2015–2025) · media');
    expect(line).toHaveTextContent(/mín .* \(2015\) · máx .* \(2022\)/);
  });
});

function rev(): number[] {
  return pool.map((p) => p.value);
}
