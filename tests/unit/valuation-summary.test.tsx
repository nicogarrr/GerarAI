import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import ValuationSummaryGrid, { ValuationSummaryCard } from '@/components/research/ValuationSummaryGrid';
import { healthMissingLabel, safetyMargin, type ValuationSummary } from '@/lib/research/valuation-summary';
import { getValuationSummaries } from '@/lib/actions/valuation-summary.actions';
vi.mock('@/lib/actions/valuation-summary.actions', () => ({ getValuationSummaries: vi.fn() }));

export const item: ValuationSummary = {
  ticker: 'DEMO', fair_value: { value: 100, currency: 'USD', label: 'Motor de valoración', as_of: '2026-10-29', publishable: true, stale: false },
  reverse_dcf: { status: 'ok', required_revenue_growth: .08, as_of: '2026-10-29', source: 'Modelo fundamental persistido', market_price: 80, model_version_id: 1 },
  health: { status: 'not_evaluable', notice: 'Indicadores contables, no recomendación ni probabilidad de quiebra.', period_end: '2025-12-31',
    piotroski: { score: null, evaluated: 1, total: 9, methodology_url: 'https://example.com/piotroski', signals: [{ id: 'roa', label: 'Rentabilidad positiva', formula: 'NI / A > 0', point: 1, missing_input: null, evidence: [{ fact_id: 4, metric: 'net_income', value: 10, unit: 'USD', period_end: '2025-12-31', source_type: 'SEC', source_url: 'https://www.sec.gov/test' }] }] },
    altman: { score: null, status: 'not_evaluable', variant: 'Z_double_prime', reason: 'retained_earnings:FY2025', methodology_url: 'https://example.com/altman' } },
};
const quote = { symbol: 'DEMO', price: 80, currency: 'USD' };

describe('shared valuation', () => {
  it('distinguishes discount-to-value from upside and rejects mismatches', () => {
    expect(safetyMargin(80, 'USD', item.fair_value)).toBeCloseTo(.2);
    expect(safetyMargin(120, 'USD', item.fair_value)).toBeCloseTo(-.2);
    for (const price of [null, 0, -1, NaN, Infinity]) expect(safetyMargin(price, 'USD', item.fair_value)).toBeNull();
    expect(safetyMargin(80, 'EUR', item.fair_value)).toBeNull();
    expect(safetyMargin(80, null, item.fair_value)).toBeNull();
    expect(safetyMargin(80, 'USD', { ...item.fair_value, publishable: false })).toBeNull();
    expect(safetyMargin(80, 'USD', { ...item.fair_value, value: NaN })).toBeNull();
  });
  it('compares London pence quotes in pounds, never GBp as GBP', () => {
    // Valor justo 15 £; cotización 1.200 GBp = 12 £ -> (15 - 12) / 15 = 20 %.
    const gbp = { ...item.fair_value, value: 15, currency: 'GBP' };
    expect(safetyMargin(1200, 'GBp', gbp)).toBeCloseTo(.2);
    expect(safetyMargin(1200, 'GBX', gbp)).toBeCloseTo(.2);
    expect(safetyMargin(12, 'GBP', gbp)).toBeCloseTo(.2);
    // Un valor justo rotulado en peniques no se compara a ciegas.
    expect(safetyMargin(12, 'GBP', { ...gbp, currency: 'GBp' })).toBeNull();
  });
  it('renders sourced points, dated model, partial not scored as zero', () => {
    render(<ValuationSummaryCard item={item} quote={quote} />);
    expect(screen.getByText('No evaluable (1/9 puntos con datos)')).toBeInTheDocument();
    expect(screen.getByText((text) => /^20[,.]0?0?\s*%$/.test(text))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Beneficio neto: 10 USD/ })).toHaveAttribute('href', 'https://www.sec.gov/test');
    expect(screen.getByText(/precio del modelo/)).toBeInTheDocument();
  });
  it('renders unavailable values and full scores without false certainty', () => {
    const copy = structuredClone(item);
    copy.fair_value.value = null;
    copy.fair_value.stale = true;
    copy.reverse_dcf = { ...copy.reverse_dcf, status: 'not_evaluable', as_of: null };
    copy.health.piotroski.score = 7;
    copy.health.piotroski.signals[0].point = null;
    copy.health.piotroski.signals[0].missing_input = 'total_assets';
    copy.health.piotroski.signals[0].evidence[0].source_url = 'http://untrusted';
    copy.health.altman.score = 2.5;
    copy.health.reason = 'Datos incompletos';
    render(<ValuationSummaryCard item={copy} quote={quote} />);
    expect(screen.getByText('7/9')).toBeInTheDocument();
    expect(screen.getByText('Datos incompletos')).toBeInTheDocument();
  });
  it('loads a batch and does not show old symbols after a change', async () => {
    vi.mocked(getValuationSummaries).mockResolvedValue({ DEMO: item });
    const view = render(<ValuationSummaryGrid quotes={[quote]} />);
    await waitFor(() => expect(screen.getByRole('link', { name: 'DEMO' })).toBeInTheDocument());
    vi.mocked(getValuationSummaries).mockResolvedValue({});
    view.rerender(<ValuationSummaryGrid quotes={[{ ...quote, symbol: 'OTHER' }]} />);
    await waitFor(() => expect(screen.getByText(/Sin empresas/)).toBeInTheDocument());
    expect(screen.queryByRole('link', { name: 'DEMO' })).not.toBeInTheDocument();
  });
  it('handles network failure and empty lists', async () => {
    vi.mocked(getValuationSummaries).mockRejectedValue(new Error('down'));
    const view = render(<ValuationSummaryGrid quotes={[quote]} />);
    await waitFor(() => expect(screen.getByText(/no está disponible ahora/)).toBeInTheDocument());
    view.rerender(<ValuationSummaryGrid quotes={[]} />);
    expect(view.container).toBeEmptyDOMElement();
  });
  it('names missing inputs and evidence in Spanish, not backend keys', () => {
    const copy = structuredClone(item);
    copy.health.piotroski.signals[0].point = null;
    copy.health.piotroski.signals[0].missing_input = 'total_assets:FY2024';
    render(<ValuationSummaryCard item={copy} quote={quote} />);
    expect(screen.getByText('Dato pendiente: Activos totales (ejercicio 2024)')).toBeInTheDocument();
    expect(screen.getByText('Dato pendiente: Beneficios retenidos (ejercicio 2025)')).toBeInTheDocument();
    expect(screen.queryByText(/total_assets|retained_earnings|net_income/)).not.toBeInTheDocument();
  });
  it('healthMissingLabel keeps already-written reasons', () => {
    expect(healthMissingLabel('current_liabilities:FY2023')).toBe('Pasivo corriente (ejercicio 2023)');
    expect(healthMissingLabel('long_term_debt')).toBe('Deuda a largo plazo');
    expect(healthMissingLabel('periodos no comparables')).toBe('periodos no comparables');
    expect(healthMissingLabel('denominador no positivo')).toBe('denominador no positivo');
  });
});

describe('valuation summary tap targets (mobile ≥44 px)', () => {
  it('ticker link, methodology links and the details toggle are 44 px tall', () => {
    render(<ValuationSummaryCard item={item} quote={quote} />);
    const targets = [
      screen.getByRole('link', { name: 'DEMO' }),
      screen.getByRole('link', { name: 'Método Piotroski' }),
      screen.getByRole('link', { name: 'Método Altman' }),
      screen.getByText(/Ver puntos, fuentes/),
    ];
    for (const el of targets) expect(el.className).toMatch(/min-h-\[44px\]/);
  });
});
