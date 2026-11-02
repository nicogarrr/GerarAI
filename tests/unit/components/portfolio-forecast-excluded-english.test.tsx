import { beforeAll, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import PortfolioForecast from '@/components/portfolio/PortfolioForecast';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import { forecastExcludedReason, valuationHoldReason } from '@/lib/portfolio/forecast-excluded-reason';

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as any;
});

// Textos tal cual los manda /api/portfolio/forecast (routes/portfolio.py).
const BACKEND: Array<[string, string, string]> = [
  ['no_published_thesis', 'Sin tesis publicada vigente: excluida de la previsión.', 'No current published thesis: excluded from the forecast.'],
  ['no_published_thesis', 'Sin tesis publicada vigente (hay borrador sin publicar): excluida de la previsión.',
    'No current published thesis (there is an unpublished draft): excluded from the forecast.'],
  ['valuation_basis_unverified', 'ADR sin valores por acción cotizada: comparación con el precio no verificada (N/D).',
    'ADR without values per listed share: comparison with the price not verified (N/A).'],
  ['valuation_basis_unverified', 'Moneda de la posición distinta de la moneda de cotización de la compañía: comparación sin conversión verificada (N/D).',
    'Position currency differs from the company’s trading currency: comparison without a verified conversion (N/A).'],
  ['valuation_basis_unverified', 'Base de valoración no verificada (tesis sin value_per_share_basis del motor): comparación con el precio N/D, nunca asumida.',
    'Unverified valuation basis (thesis without the engine’s value_per_share_basis): comparison with the price N/A, never assumed.'],
  ['no_computable_intrinsic', 'Tesis sin valores intrinsecos computables.', 'Thesis without computable intrinsic values.'],
  ['no_base_value', 'Sin valor en moneda base (conversión N/D): no se suma a la cartera.', 'No value in the base currency (conversion N/A): not added to the portfolio.'],
  ['valuation_hold', 'Valoración pendiente: split 2:1 de 2026-06-01 aplicado sin precio post-split verificado: valoracion no disponible.',
    'Valuation pending: 2:1 split of 2026-06-01 applied without a verified post-split price: valuation not available.'],
];

const en = createTranslator('en');
const es = createTranslator('es');

describe('forecast exclusions in English', () => {
  it.each(BACKEND)('%s: %s', (code, spanish, english) => {
    expect(forecastExcludedReason({ reason_code: code, reason: spanish }, 'en', en)).toBe(english);
    expect(forecastExcludedReason({ reason_code: code, reason: spanish }, 'es', es)).toBe(spanish);
  });

  it('unknown codes and texts pass through unchanged', () => {
    expect(forecastExcludedReason({ reason_code: 'nuevo', reason: 'Motivo nuevo' }, 'en', en)).toBe('Motivo nuevo');
    expect(valuationHoldReason('otro motivo', 'en')).toBe('otro motivo');
    expect(valuationHoldReason('split 3:1 de 2026-01-02 aplicado sin precio post-split verificado: valoracion no disponible', 'es'))
      .toBe('split 3:1 de 2026-01-02 aplicado sin precio post-split verificado: valoracion no disponible');
  });

  it('the forecast panel lists the excluded positions in English', () => {
    const forecast: any = {
      as_of: '2026-10-01', base_currency: 'EUR', portfolio: null, positions: [], assumptions: [],
      excluded: BACKEND.map(([code, reason], i) => ({ ticker: `T${i}`, weight: 0.1, reason, reason_code: code })),
    };
    render(<PortfolioForecast forecast={forecast} ti={en} f={createFormatters('en')} />);
    for (const [, , english] of BACKEND) expect(screen.getByText(english, { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/Sin tesis publicada|excluida de la previsión|Valoración pendiente/)).not.toBeInTheDocument();
  });
});
