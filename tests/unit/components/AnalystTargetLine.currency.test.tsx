import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/analyst-targets.actions', () => ({
    getListingAnalystTargets: vi.fn(),
}));

import { getListingAnalystTargets } from '@/lib/actions/analyst-targets.actions';
import { requestCache } from '@/lib/cache/requestCache';
import AnalystTargetLine from '@/components/common/AnalystTargetLine';
import { convertWithPortfolioFx } from '@/lib/analyst-target-currency';

// ASML comprada en EUR: Yahoo solo da el consenso del ADR en USD. Nunca un
// objetivo en USD junto a un precio en EUR sin decirlo (Nico, 29-oct-2026).
const mocked = vi.mocked(getListingAnalystTargets);
const USD_TARGET = {
    status: 'available', mean: 1000, currency: 'USD', firms: 20, fetchedAt: null, source: 'Yahoo Finance', note: null,
} as never;

beforeEach(() => {
    requestCache.clear();
    mocked.mockResolvedValue(USD_TARGET);
});

describe('objetivo de analistas en otra divisa', () => {
    it('con tipo de cambio de la cartera: convertido a EUR, con nota y recorrido', async () => {
        render(
            <AnalystTargetLine symbol="ASML" currency="EUR" referencePrice={800} baseCurrency="EUR"
                fxRates={[{ scope: 'positions', currency: 'USD', rate: 0.9, as_of: '2026-10-29' }]} />,
        );
        expect(await screen.findByText(/900,00/)).toBeInTheDocument();
        expect(screen.getByText('(convertido de USD)')).toBeInTheDocument();
        expect(screen.getByText(/\+12,5/)).toBeInTheDocument();
        expect(screen.queryByText(/1[.,]000/)).toBeNull();
    });

    it('sin tipo de cambio: se queda en USD, etiquetado «(ADR, USD)» y sin recorrido', async () => {
        render(<AnalystTargetLine symbol="ASML" currency="EUR" referencePrice={800} />);
        expect(await screen.findByText('(ADR, USD)')).toBeInTheDocument();
        expect(screen.getByText(/1[.,]000/)).toBeInTheDocument();
        expect(screen.queryByText(/%/)).toBeNull();
    });

    it('misma divisa: sin nota', async () => {
        render(<AnalystTargetLine symbol="AAPL" currency="USD" referencePrice={800} />);
        expect(await screen.findByText(/1[.,]000/)).toBeInTheDocument();
        expect(screen.queryByText(/convertido|ADR/)).toBeNull();
    });
});

describe('convertWithPortfolioFx', () => {
    const rates = [{ scope: 'positions', currency: 'USD', rate: 0.9 }, { scope: 'positions', currency: 'GBP', rate: 1.2 }];
    it('convierte vía la divisa base y devuelve null si falta un tipo', () => {
        expect(convertWithPortfolioFx(1000, 'USD', 'EUR', rates, 'EUR')).toBeCloseTo(900);
        expect(convertWithPortfolioFx(900, 'EUR', 'USD', rates, 'EUR')).toBeCloseTo(1000);
        expect(convertWithPortfolioFx(120, 'USD', 'GBP', rates, 'EUR')).toBeCloseTo(90);
        expect(convertWithPortfolioFx(1000, 'USD', 'CHF', rates, 'EUR')).toBeNull();
        expect(convertWithPortfolioFx(1000, 'USD', 'EUR', null, 'EUR')).toBeNull();
        expect(convertWithPortfolioFx(1000, 'USD', 'EUR', [{ currency: 'USD', rate: 0 }], 'EUR')).toBeNull();
    });
});
