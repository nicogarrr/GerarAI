import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('@/lib/actions/ownership.actions', () => ({
    getOwnershipManagers: async () => ({ managers: [{ cik: '1', name: 'Fund' }], limitations: [] }),
    getManagerHoldings: async () => ({ status: 'unavailable', holdings: [] }),
    getManagerChanges: async () => ({ status: 'insufficient_history', changes: [] }),
}));
vi.mock('@/app/(root)/ownership/SyncButton', () => ({ default: () => null }));
vi.mock('@/app/(root)/inversores/_components/SyncPortfoliosButton', () => ({ SyncPortfoliosButton: ({ label }: { label: string }) => <button type="button">{label}</button> }));

import OwnershipPage from '@/app/(root)/ownership/page';

describe('Movimientos 13F en inglés', () => {
    it('en inglés', async () => {
        mocks.locale = 'en';
        render(await OwnershipPage({ searchParams: Promise.resolve({}) }));
        expect(screen.getByRole('heading', { level: 1, name: '13F moves' })).toBeTruthy();
        expect(screen.getByText('By manager')).toBeTruthy();
        expect(screen.getByText('No 13F data yet')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Sync 13F' })).toBeTruthy();
        expect(screen.getByText('Two stored 13F reports are needed to compare; it will be available after the next quarter.')).toBeTruthy();
    });

    it('en español no cambia', async () => {
        mocks.locale = 'es';
        render(await OwnershipPage({ searchParams: Promise.resolve({}) }));
        expect(screen.getByRole('heading', { level: 1, name: 'Movimientos 13F' })).toBeTruthy();
        expect(screen.getByText('Sin datos 13F todavía')).toBeTruthy();
    });
});
