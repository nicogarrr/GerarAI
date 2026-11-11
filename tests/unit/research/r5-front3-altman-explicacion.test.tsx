import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { ValuationSummaryCard } from '@/components/research/ValuationSummaryGrid';
import { LocaleProvider } from '@/lib/i18n/client';
import type { ValuationSummary } from '@/lib/research/valuation-summary';
vi.mock('@/lib/actions/valuation-summary.actions', () => ({ getValuationSummaries: vi.fn() }));

// r5-front3: «Altman Z''» salía como etiqueta críptica sin explicación en castellano (AUDIT fa-informe #14).
// Ahora un desplegable tocable dice qué mide, las referencias del autor y la fórmula, como la «Fórmula» del consenso.
const quote = { symbol: 'DEMO', price: 80, currency: 'USD' };
const scored: ValuationSummary = {
  ticker: 'DEMO', fair_value: { value: 100, currency: 'USD', label: 'Motor de valoración', as_of: '2026-10-29', publishable: true, stale: false },
  reverse_dcf: { status: 'ok', required_revenue_growth: .08, as_of: '2026-10-29', source: 'Modelo fundamental persistido', market_price: 80, model_version_id: 1 },
  health: { status: 'ok', notice: 'Indicadores contables, no recomendación ni probabilidad de quiebra.', period_end: '2025-12-31',
    piotroski: { score: 7, evaluated: 9, total: 9, methodology_url: 'https://example.com/piotroski', signals: [] },
    altman: { score: 3.21, status: 'ok', variant: 'Z_double_prime', methodology_url: 'https://example.com/altman' } },
};

describe('Altman Z\'\': explicación tocable', () => {
  it('en castellano: qué mide, zonas de referencia y fórmula con coma decimal', () => {
    render(<ValuationSummaryCard item={scored} quote={quote} />);
    const box = screen.getByTestId('altman-explain');
    const summary = within(box).getByText('¿Qué es?');
    expect(summary.tagName).toBe('SUMMARY');
    fireEvent.click(summary);
    expect(box.textContent).toMatch(/riesgo de quiebra/);
    expect(box.textContent).toContain('por encima de 2,60, zona segura');
    expect(box.textContent).toContain('por debajo de 1,10');
    expect(box.textContent).toContain('6,56 × fondo de maniobra/activos');
  });
  it('en inglés también', () => {
    render(<LocaleProvider locale="en"><ValuationSummaryCard item={scored} quote={quote} /></LocaleProvider>);
    const box = screen.getByTestId('altman-explain');
    expect(within(box).getByText('What is it?')).toBeTruthy();
    expect(box.textContent).toContain('above 2.60, safe zone');
    expect(box.textContent).not.toMatch(/zona|activos/);
  });
});
