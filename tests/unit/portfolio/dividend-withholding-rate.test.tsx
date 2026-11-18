/**
 * Contrato de escala de la retención en origen (18-nov-2026): el API envía
 * `source_withholding_rate` como RATIO (0.15 = 15 %; lo fija
 * data-engine/tests/test_dividend_projection.py) y el frontend lo pinta con
 * formatPercent por defecto (fromRatio: true, lib/format.ts). Si alguien
 * cambia la escala en un solo lado, US pasaría de 15,0 % a 1500,0 % o a 0,2 %.
 */
import { render } from '@testing-library/react';
import { beforeAll, describe, expect, it } from 'vitest';

import PortfolioDividends from '@/components/portfolio/PortfolioDividends';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const projection: any = {
    as_of: '2026-11-17', base_currency: 'EUR', horizon_months: 3, label: 'Proyección',
    coverage: { fx_missing: [], sin_datos: [], uncertain_dividends: [], unknown_source_withholding: [], unverified_reasons: [] },
    months: [
        { month: '2026-12', covered_tickers: ['AAPL'], excluded_tickers: [], gross_base: 120.5, gross_unverified_base: null, source_withheld_base: 18.08 },
    ],
    fiscal_by_year: {}, fiscal_conditions: [], sources: [],
    gross_summary: { gross_total_base: 120.5, gross_unverified_base: 0, complete: true },
    declared_future: [],
    positions: [
        { ticker: 'AAPL', quantity: 10, gross_base: 120.5, frequency_last_year: 4, source_withheld_base: 18.08, domicile_country: 'US', withholding_kind: 'known', source_withholding_rate: 0.15, scenario_conditions: [], unverified_reason: null },
    ],
};

describe('retención en origen: el ratio del API se pinta como porcentaje', () => {
    beforeAll(() => {
        if (typeof window.matchMedia !== 'function') {
            window.matchMedia = ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })) as typeof window.matchMedia;
        }
    });

    it('0.15 (US) se muestra como 15,0 %, ni 1500 % ni 0,2 %', () => {
        const { container } = render(<PortfolioDividends projection={projection} />);
        const text = container.textContent ?? '';
        expect(text).toMatch(/15,0\s*%/);
        expect(text).not.toContain('1500');
        expect(text).not.toMatch(/0,2\s*%/);
    });

    it('tasa null degrada a N/D sin inventar cifra', () => {
        const sinTasa = {
            ...projection,
            positions: [{ ...projection.positions[0], source_withholding_rate: null, unverified_reason: ['sin_fuente'] }],
        };
        const { container } = render(<PortfolioDividends projection={sinTasa} />);
        expect(container.textContent ?? '').not.toMatch(/NaN|1500/);
    });
});
