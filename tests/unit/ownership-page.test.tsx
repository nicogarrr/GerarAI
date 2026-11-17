// La página es un server component traducido con getT(): lib/i18n/server lee
// la cookie de locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ManagerHoldings } from '@/lib/actions/ownership.actions';

/**
 * /ownership: la proveniencia puede llegar con fetched_at nulo (el backend
 * declara nula una fecha de descarga que no conoce en vez de fabricar el
 * momento de la petición). Sin fecha real NO se pinta la etiqueta «Datos
 * obtenidos el …»: un «N/D» ahí sugeriría una descarga sin datar.
 */
const getOwnershipManagers = vi.fn();
const getManagerHoldings = vi.fn();
const getManagerChanges = vi.fn();
vi.mock('@/lib/actions/ownership.actions', () => ({
    getOwnershipManagers: () => getOwnershipManagers(),
    getManagerHoldings: () => getManagerHoldings(),
    getManagerChanges: () => getManagerChanges(),
}));
vi.mock('@/app/(root)/ownership/SyncButton', () => ({ default: () => null }));
vi.mock('@/app/(root)/ownership/_components/MostBought', () => ({ MostBought: () => null }));
vi.mock('@/app/(root)/ownership/_components/Overlap', () => ({ Overlap: () => null }));
vi.mock('@/app/(root)/inversores/_components/SyncPortfoliosButton', () => ({ SyncPortfoliosButton: () => null }));

import OwnershipPage from '@/app/(root)/ownership/page';

const holdingsWith = (fetched_at: string | null): ManagerHoldings => ({
    cik: '0001067983',
    manager: 'Berkshire Hathaway',
    status: 'ok',
    report_date: '2026-09-30',
    holdings: [],
    provenance: {
        source: 'SEC EDGAR',
        source_kind: 'official',
        source_url: null,
        fetched_at,
        coverage: '13F',
    },
});

beforeEach(() => {
    getOwnershipManagers.mockReset();
    getManagerHoldings.mockReset();
    getManagerChanges.mockReset();
    getOwnershipManagers.mockResolvedValue({
        managers: [{ cik: '0001067983', name: 'Berkshire Hathaway' }],
        limitations: [],
    });
    getManagerChanges.mockResolvedValue(null);
});

describe('página de participaciones (ownership)', () => {
    it('proveniencia con fetched_at nulo: no pinta la etiqueta «Datos obtenidos»', async () => {
        getManagerHoldings.mockResolvedValue(holdingsWith(null));
        render(await OwnershipPage({ searchParams: Promise.resolve({}) }));
        expect(screen.queryByText(/Datos obtenidos/)).not.toBeInTheDocument();
    });

    it('proveniencia con fetched_at real: pinta la etiqueta con la fecha', async () => {
        getManagerHoldings.mockResolvedValue(holdingsWith('2026-11-10T17:30:00+00:00'));
        render(await OwnershipPage({ searchParams: Promise.resolve({}) }));
        expect(screen.getByText(/Datos obtenidos el/)).toBeInTheDocument();
    });
});
