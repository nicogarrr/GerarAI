import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getWatchlistEntryData, getWatchlistState, fetchDatedChanges, getFairValueReading, getScreenerStocksReal } = vi.hoisted(() => ({
    getWatchlistEntryData: vi.fn<(...args: any[]) => any>(),
    getWatchlistState: vi.fn<(...args: any[]) => any>(),
    fetchDatedChanges: vi.fn<(...args: any[]) => any>(async () => ({})),
    getFairValueReading: vi.fn<(...args: any[]) => any>(),
    getScreenerStocksReal: vi.fn<(...args: any[]) => any>(async () => []),
}));
vi.mock('@/lib/actions/watchlist.actions', () => ({ getWatchlistEntryData, getWatchlistState }));
vi.mock('@/lib/market/dated-change', () => ({ fetchDatedChanges }));
vi.mock('@/lib/actions/screener.actions', () => ({ getFairValueReading, getScreenerStocksReal }));

import { getHomeWatchlistPreview, getHomeOpportunities } from '@/lib/actions/home-overview.actions';
import { DCF_MIN_UPSIDE_PCT } from '@/lib/overview/dcf-candidates';

beforeEach(() => {
    vi.resetAllMocks();
    fetchDatedChanges.mockResolvedValue({});
    getScreenerStocksReal.mockResolvedValue([]);
});

describe('getHomeWatchlistPreview', () => {
    it('watchlist no disponible -> se declara, sin items', async () => {
        getWatchlistState.mockResolvedValue({ items: [], unavailable: true });
        expect(await getHomeWatchlistPreview(5)).toEqual({ unavailable: true, total: 0, items: [] });
    });

    it('cotización viva manda; un cierre usa el cierre datado común (misma fecha que watchlist)', async () => {
        getWatchlistState.mockResolvedValue({
            items: [{ symbol: 'AAPL' }, { symbol: 'CGEO.L' }],
            unavailable: false,
        });
        getWatchlistEntryData.mockImplementation(async (sym: string) => sym === 'AAPL'
            ? { symbol: 'AAPL', name: 'Apple', price: 150, currency: 'USD', changePercent: 1.2, priceKind: 'live', priceAsOf: null }
            : { symbol: 'CGEO.L', name: 'CGeo', price: 3.25, currency: 'GBp', changePercent: 0, priceKind: 'close', priceAsOf: '2026-10-19' });
        fetchDatedChanges.mockResolvedValue({ 'CGEO.L': { price: 3.18, changePercent: -0.82, currency: 'GBp', date: '2026-10-16' } });
        const preview = await getHomeWatchlistPreview(5);
        expect(preview.total).toBe(2);
        expect(preview.items[0]).toMatchObject({ symbol: 'AAPL', price: 150, priceKind: 'live' }); // viva: dated ignorado
        expect(preview.items[1]).toMatchObject({ symbol: 'CGEO.L', price: 3.18, changePercent: -0.82, priceKind: 'close', priceAsOf: '2026-10-16' });
    });

    it('un símbolo que falla queda en N/D; nunca se fabrica un 0', async () => {
        getWatchlistState.mockResolvedValue({ items: [{ symbol: 'ROTO' }], unavailable: false });
        getWatchlistEntryData.mockRejectedValue(new Error('proveedor caído'));
        const preview = await getHomeWatchlistPreview(5);
        expect(preview.items[0]).toEqual({ symbol: 'ROTO', name: 'ROTO', price: null, currency: null, changePercent: null, priceKind: null, priceAsOf: null });
    });

    it('respeta el límite de la página pero total cuenta la lista entera', async () => {
        getWatchlistState.mockResolvedValue({ items: [{ symbol: 'A' }, { symbol: 'B' }, { symbol: 'C' }], unavailable: false });
        getWatchlistEntryData.mockImplementation(async (symbol: string) => ({ symbol, name: symbol, price: 1, currency: 'USD', changePercent: 0, priceKind: 'live', priceAsOf: null }));
        const preview = await getHomeWatchlistPreview(2);
        expect(preview.total).toBe(3);
        expect(preview.items).toHaveLength(2);
    });
});

describe('getHomeOpportunities', () => {
    const row = (symbol: string, has = true) => ({ symbol, has_fundamentals: has });

    it('candidatas con fundamentales primero, acotadas a candidateLimit', async () => {
        getScreenerStocksReal.mockResolvedValue([row('SIN1', false), row('CON1'), row('CON2'), row('SIN2', false)]);
        getWatchlistEntryData.mockImplementation(async (symbol: string) => ({ symbol, name: symbol, price: 100, currency: 'USD' }));
        getFairValueReading.mockResolvedValue({ value: 200, publishable: true, label: 'Motor', asOf: '2026-10-27' });
        const result = await getHomeOpportunities({ marketCapMoreThan: 1e9, limit: 50, candidateLimit: 3 });
        expect(result.map((r) => (r.opportunity?.symbol ?? ''))).toEqual(['CON1', 'CON2', 'SIN1']);
    });

    it('upside por encima del mínimo -> oportunidad; por debajo -> evaluada sin oportunidad', async () => {
        getScreenerStocksReal.mockResolvedValue([row('BARATA'), row('CARA')]);
        getWatchlistEntryData.mockImplementation(async (symbol: string) => ({ symbol, name: symbol, price: 100, currency: 'USD' }));
        getFairValueReading.mockImplementation(async (sym: string) =>
            sym === 'BARATA' ? { value: 150, publishable: true, label: 'Tesis', asOf: null } : { value: 100 + DCF_MIN_UPSIDE_PCT, publishable: true, label: 'Tesis', asOf: null });
        const [barata, cara] = await getHomeOpportunities({ marketCapMoreThan: 0, limit: 50, candidateLimit: 10 });
        expect(barata).toMatchObject({ evaluated: true });
        expect(barata.opportunity).toMatchObject({ symbol: 'BARATA', fairValue: 150, orientation: false });
        expect(cara).toEqual({ evaluated: true, opportunity: null }); // upside = umbral exacto no supera
    });

    it('DCF no publicable -> orientation true (orientación, no valoración final)', async () => {
        getScreenerStocksReal.mockResolvedValue([row('X')]);
        getWatchlistEntryData.mockResolvedValue({ symbol: 'X', name: 'X', price: 100, currency: 'EUR' });
        getFairValueReading.mockResolvedValue({ value: 200, publishable: false, label: 'Motor de valoración', asOf: '2026-10-27' });
        const [x] = await getHomeOpportunities({ marketCapMoreThan: 0, limit: 50, candidateLimit: 10 });
        expect(x.opportunity).toMatchObject({ orientation: true, fairValueLabel: 'Motor de valoración' });
    });

    it('sin lectura o sin precio -> no evaluada; un fallo no tira el lote', async () => {
        getScreenerStocksReal.mockResolvedValue([row('A'), row('B'), row('C')]);
        getFairValueReading.mockImplementation(async (sym: string) => { if (sym === 'C') throw new Error('caído'); return null; });
        getWatchlistEntryData.mockImplementation(async (symbol: string) => ({ symbol, name: symbol, price: symbol === 'B' ? 0 : 100, currency: 'USD' }));
        const result = await getHomeOpportunities({ marketCapMoreThan: 0, limit: 50, candidateLimit: 10 });
        expect(result).toEqual([
            { evaluated: false, opportunity: null },
            { evaluated: false, opportunity: null },
            { evaluated: false, opportunity: null },
        ]);
    });
});
