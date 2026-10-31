import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/analyst-targets.actions', () => ({
    getListingAnalystTargetsBatch: vi.fn(),
}));

import { getListingAnalystTargetsBatch } from '@/lib/actions/analyst-targets.actions';
import { requestCache } from '@/lib/cache/requestCache';
import AnalystTargetLine from '@/components/common/AnalystTargetLine';
import { convertWithPortfolioFx } from '@/lib/analyst-target-currency';

// Londres: Yahoo da el objetivo en peniques (el backend lo declara «GBX").
// La watchlist pinta el precio en libras (GBP) y Cartera en peniques (GBp).
// Valores derivados a mano: objetivo 300 p = 3,00 £; precio 2,50 £ = 250 p;
// recorrido (3,00 / 2,50 − 1) × 100 = +20,0 %.
const mocked = vi.mocked(getListingAnalystTargetsBatch);
const target = (mean: number, currency: string) =>
    ({ status: 'available', mean, currency, firms: 12, fetchedAt: null, source: 'Yahoo Finance', note: null }) as never;

beforeEach(() => {
    requestCache.clear();
});

describe('objetivo de analistas en peniques', () => {
    it('watchlist (fila en GBP): objetivo en GBX convertido exacto a libras, con recorrido', async () => {
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, target(300, 'GBX')])));
        render(<AnalystTargetLine symbol="CGEO.L" currency="GBP" referencePrice={2.5} />);
        expect(await screen.findByText(/\+20,0/)).toBeInTheDocument();
        expect(screen.getByText(/3,00/)).toBeInTheDocument();
        expect(screen.queryByText('(en GBX)')).toBeNull();
    });

    it('cartera (fila en GBp): objetivo en GBX es la misma unidad', async () => {
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, target(300, 'GBX')])));
        render(<AnalystTargetLine symbol="CGEO.L" currency="GBp" referencePrice={250} />);
        expect(await screen.findByText(/\+20,0/)).toBeInTheDocument();
    });

    it('cartera (fila en GBp): un objetivo en libras no se lee como peniques (×100)', async () => {
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, target(3, 'GBP')])));
        render(<AnalystTargetLine symbol="CGEO.L" currency="GBp" referencePrice={250} />);
        expect(await screen.findByText(/\+20,0/)).toBeInTheDocument();
        expect(screen.queryByText(/98,8/)).toBeNull();
    });

    it('peniques a otra divisa con los tipos de la cartera', () => {
        const rates = [{ scope: 'positions', currency: 'GBP', rate: 1.15 }];
        expect(convertWithPortfolioFx(300, 'GBX', 'EUR', rates, 'EUR')).toBeCloseTo(3.45, 10);
        expect(convertWithPortfolioFx(3, 'GBP', 'GBp', null, null)).toBeCloseTo(300, 10);
        expect(convertWithPortfolioFx(1000, 'USD', 'EUR', [{ currency: 'USD', rate: 0.9 }], 'EUR')).toBeCloseTo(900, 10);
    });
});
