import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ValuationSummaryCard } from '@/components/research/ValuationSummaryGrid';
import { reverseBaseRateMissing, type ValuationSummary } from '@/lib/research/valuation-summary';

const item: ValuationSummary = {
  ticker: 'DEMO', fair_value: { value: 100, currency: 'USD', label: 'Motor de valoración', as_of: '2026-10-29', publishable: true, stale: false },
  reverse_dcf: { status: 'ok', required_revenue_growth: .08, as_of: '2026-10-29', source: 'Modelo fundamental persistido', market_price: 80, model_version_id: 1 },
  health: { status: 'not_evaluable', notice: 'Indicadores contables, no recomendación ni probabilidad de quiebra.', period_end: '2025-12-31',
    piotroski: { score: null, evaluated: 0, total: 9, methodology_url: 'https://example.com/piotroski', signals: [] },
    altman: { score: null, status: 'not_evaluable', variant: 'Z_double_prime', methodology_url: 'https://example.com/altman' } },
};
const quote = { symbol: 'DEMO', price: 80, currency: 'USD' };
const HORIZON = 'la tasa base mide plazos de 1, 2, 3, 5, 7 y 10 años y el DCF inverso usa 8: no se compara un plazo distinto';

/**
 * #5381 (r5-valor) añadió en el backend el motivo del N/D de la tasa base del
 * DCF inverso ({share: null, reason}), pero la tarjeta solo pintaba la cifra:
 * con share null no salía NADA y el lector no sabía si faltaba o no aplicaba.
 */
describe('DCF inverso: tasa base N/D con su motivo', () => {
  it('con share null y motivo, la tarjeta dice «Tasa base N/D» y por qué', () => {
    render(<ValuationSummaryCard item={{ ...item, reverse_dcf: { ...item.reverse_dcf, base_rate_check: { share: null, horizon_years: 8, reason: HORIZON } } }} quote={quote} />);
    const nd = screen.getByTestId('reverse-dcf-base-rate-missing');
    expect(nd.textContent).toContain('Tasa base N/D');
    expect(nd.textContent).toContain('mide plazos de 1, 2, 3, 5, 7 y 10 años');
    expect(screen.queryByTestId('reverse-dcf-base-rate-reach')).toBeNull();
  });

  it('el motivo de divisa sin tipo oficial también se ve', () => {
    const reason = 'sin tipo de cambio oficial TWD/USD: los tramos de tamaño de la tasa base están en dólares';
    render(<ValuationSummaryCard item={{ ...item, reverse_dcf: { ...item.reverse_dcf, base_rate_check: { share: null, reason } } }} quote={quote} />);
    expect(screen.getByTestId('reverse-dcf-base-rate-missing').textContent).toContain(reason);
  });

  it('sin motivo, sin cifra o con el DCF inverso N/D no se añade la línea', () => {
    const { unmount } = render(<ValuationSummaryCard item={{ ...item, reverse_dcf: { ...item.reverse_dcf, base_rate_check: { share: null } } }} quote={quote} />);
    expect(screen.queryByTestId('reverse-dcf-base-rate-missing')).toBeNull();
    unmount();
    const r2 = render(<ValuationSummaryCard item={{ ...item, reverse_dcf: { ...item.reverse_dcf, status: 'insufficient_data', required_revenue_growth: null, reason: 'Sin modelo', base_rate_check: { share: null, reason: HORIZON } } }} quote={quote} />);
    expect(screen.queryByTestId('reverse-dcf-base-rate-missing')).toBeNull();
    r2.unmount();
    render(<ValuationSummaryCard item={{ ...item, reverse_dcf: { ...item.reverse_dcf, base_rate_check: { share: 0.2, bound: '=', horizon_years: 5, reason: null } } }} quote={quote} />);
    expect(screen.queryByTestId('reverse-dcf-base-rate-missing')).toBeNull();
    expect(screen.getByTestId('reverse-dcf-base-rate-reach')).toBeInTheDocument();
  });

  it('en inglés el motivo de plazo se traduce; los demás se dejan tal cual', () => {
    expect(reverseBaseRateMissing({ share: null, reason: HORIZON }, 'en')).toBe('the base rate measures horizons of 1, 2, 3, 5, 7 and 10 years and the reverse DCF uses 8: a different horizon is not compared');
    expect(reverseBaseRateMissing({ share: null, reason: HORIZON }, 'es')).toBe(HORIZON);
    expect(reverseBaseRateMissing({ share: 0.1, reason: HORIZON }, 'es')).toBeNull();
    expect(reverseBaseRateMissing(null, 'es')).toBeNull();
  });
});
