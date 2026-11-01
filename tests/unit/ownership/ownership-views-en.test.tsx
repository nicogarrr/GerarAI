import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('@/lib/actions/investors.actions', () => ({
    getMostBought: async () => ({ status: 'sin_datos', items: [], report_dates: [], managers_compared: 3, managers_without_history: 1, managers_partial: 0 }),
    getPortfolioOverlap: async () => ({ positions: [], not_owned: [], unresolved_positions: 0, report_dates: ['2026-09-30'], managers_with_data: 2, managers_without_data: 1, managers_partial: 0, message: null }),
}));
vi.mock('@/app/(root)/inversores/_components/SyncPortfoliosButton', () => ({ SyncPortfoliosButton: () => null }));

import { MostBought } from '@/app/(root)/ownership/_components/MostBought';
import { Overlap } from '@/app/(root)/ownership/_components/Overlap';
import { newLabel } from '@/app/(root)/inversores/_components/labels';

describe('Más compradas y solape en inglés', () => {
    it('más compradas en inglés', async () => {
        mocks.locale = 'en';
        render(await MostBought({}));
        expect(screen.getByText('No data yet: two synced quarters of 13F are needed.')).toBeTruthy();
        expect(screen.getByText(/3 compared, 1 without two quarters yet/)).toBeTruthy();
    });

    it('solape en inglés', async () => {
        mocks.locale = 'en';
        render(await Overlap({}));
        expect(screen.getByText('Bought by several, outside your portfolio')).toBeTruthy();
        expect(screen.getByText('No matches with purchases by two or more managers.')).toBeTruthy();
    });

    it('en español no cambia', async () => {
        mocks.locale = 'es';
        render(await MostBought({}));
        expect(screen.getByText('Sin datos todavía: faltan dos trimestres de 13F sincronizados.')).toBeTruthy();
        expect(screen.getByText(/3 comparados, 1 sin dos trimestres todavía/)).toBeTruthy();
        expect(newLabel(1)).toBe('1 nueva');
        expect(newLabel(2, 'en')).toBe('2 new');
    });
});
