import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, getResearchCompanyBasics, getStockQuote, getStockValuationBasics } = vi.hoisted(() => ({
    researchRequest: vi.fn<(...args: any[]) => any>(),
    getResearchCompanyBasics: vi.fn<(...args: any[]) => any>(),
    getStockQuote: vi.fn<(...args: any[]) => any>(async () => null),
    getStockValuationBasics: vi.fn<(...args: any[]) => any>(async () => null),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: async () => ({ id: 'user-1' }) }));
vi.mock('@/lib/actions/market-workspace.actions', () => ({ getResearchCompanyBasics }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getStockQuote, getStockValuationBasics }));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));

import { getWatchlistEntryData, type WatchlistEntryData } from '@/lib/actions/watchlist.actions';
import { marketCapGapReason } from '@/lib/watchlist/market-cap-gap';
import { peNdNote } from '@/lib/watchlist/pe-nd-reason';
import {
    WATCHLIST_BACKEND_DEADLINE_MS,
    WATCHLIST_QUOTE_BUDGET_MS,
    WATCHLIST_ROW_BUDGET_MS,
    withinBudget,
} from '@/lib/watchlist/read-budget';

/**
 * r5-valor3 (pista de r5-valor2, 11-nov-2026): el presupuesto de 3 s por fila
 * incluía la cotización (Finnhub → respaldo Yahoo, hasta 5 s en frío). Si la
 * cotización tardaba, la fila entera salía vacía con «la lectura tardó más de
 * 3 s» y se perdían la capitalización y el PER del backend, que ya habían
 * llegado. Ahora cada lectura tiene su propio tope, por debajo del de la fila.
 */

const BACKEND = { market_cap: 154_990_000_000, per: 29.8, currency: 'EUR', sources: ['Capitalización: yahoo', 'PER: cierre / eps_diluted FY2025 (ESEF)'] };
const QUOTE = { c: 210.7, d: 1.2, dp: 0.57, pc: 209.5, t: 1_762_876_800, kind: 'live', currency: 'EUR' };
const never = () => new Promise<never>(() => {});

/** Resuelve la entrada o devuelve 'pendiente' si no llegó dentro de `ms` (reloj simulado). */
async function entryWithin(symbol: string, ms: number): Promise<WatchlistEntryData | 'pendiente'> {
    let out: WatchlistEntryData | 'pendiente' = 'pendiente';
    void getWatchlistEntryData(symbol).then((entry) => {
        out = entry;
    });
    await vi.advanceTimersByTimeAsync(ms);
    return out;
}

beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    researchRequest.mockResolvedValue(BACKEND);
    getStockQuote.mockResolvedValue(QUOTE);
    getStockValuationBasics.mockResolvedValue(null);
});

afterEach(() => {
    vi.useRealTimers();
});

describe('los topes de cada lectura caben en el de la fila', () => {
    it('cotización < backend < fila', () => {
        expect(WATCHLIST_QUOTE_BUDGET_MS).toBeLessThan(WATCHLIST_BACKEND_DEADLINE_MS);
        expect(WATCHLIST_BACKEND_DEADLINE_MS).toBeLessThan(WATCHLIST_ROW_BUDGET_MS);
    });

    it('withinBudget: a tiempo da el valor; tarde, timedOut', async () => {
        const fast = withinBudget(Promise.resolve(7), 100);
        await vi.advanceTimersByTimeAsync(0);
        await expect(fast).resolves.toEqual({ value: 7, timedOut: false });
        const slow = withinBudget(never(), 100);
        await vi.advanceTimersByTimeAsync(101);
        await expect(slow).resolves.toEqual({ value: null, timedOut: true });
        expect(vi.getTimerCount()).toBe(0);
    });
});

describe('cotización lenta: las cifras del backend no se pierden', () => {
    it('plaza no-US (París): sin precio, pero con capitalización y PER del backend antes del corte de la fila', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'AIR.PA', name: 'Airbus SE', exchange: 'EPA', currency: 'EUR' });
        getStockQuote.mockImplementation(never);
        const entry = await entryWithin('AIR.PA', WATCHLIST_QUOTE_BUDGET_MS + 1);
        expect(entry).not.toBe('pendiente');
        const row = entry as WatchlistEntryData;
        expect(row.price).toBeNull();
        expect(row.quoteTimedOut).toBe(true);
        expect(row.marketCap).toBe(154_990_000_000);
        expect(row.peRatio).toBe(29.8);
        expect(marketCapGapReason({ ...row, timedOut: false })).toBeNull();
    });

    it('PER N/D explicado por el backend: con la cotización cortada se lee su motivo, no «tardó más de 3 s»', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'ERF.PA', name: 'Eurofins', exchange: 'EPA', currency: 'EUR' });
        getStockQuote.mockImplementation(never);
        researchRequest.mockResolvedValue({
            market_cap: 10_000_000_000, per: null, currency: 'EUR',
            sources: ['PER: N/D: el último eps_diluted anual es FY2024 (cierre 2024-12-31, hace 22 meses, más de 18): falta en la base el informe anual más reciente'],
        });
        const row = (await entryWithin('ERF.PA', WATCHLIST_QUOTE_BUDGET_MS + 1)) as WatchlistEntryData;
        expect(row).not.toBe('pendiente');
        expect(peNdNote({ ...row, timedOut: false })).toEqual({ key: 'watchlist.page.peNd.stale', params: { year: '2024' } });
    });

    it('línea US: métricas Finnhub cortadas → respaldo del backend dentro del tope', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'POOL', name: 'Pool Corp', exchange: 'NASDAQ', currency: 'USD' });
        getStockValuationBasics.mockImplementation(never);
        researchRequest.mockResolvedValue({ market_cap: 12_000_000_000, per: 27.1, currency: 'USD', sources: ['PER: cierre / eps_diluted FY2025 (SEC)'] });
        const row = (await entryWithin('POOL', WATCHLIST_QUOTE_BUDGET_MS + 1)) as WatchlistEntryData;
        expect(row).not.toBe('pendiente');
        expect(row.price).toBe(210.7);
        expect(row.quoteTimedOut).toBe(false);
        expect(row.marketCap).toBe(12_000_000_000);
        expect(row.peRatio).toBe(27.1);
    });
});

describe('backend lento: «no se pudo leer a tiempo», nunca «la fuente no lo da»', () => {
    it('con la cotización a tiempo, el precio se pinta y la capitalización N/D dice que la lectura falló', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'AIR.PA', name: 'Airbus SE', exchange: 'EPA', currency: 'EUR' });
        researchRequest.mockImplementation(never);
        const row = (await entryWithin('AIR.PA', WATCHLIST_BACKEND_DEADLINE_MS + 1)) as WatchlistEntryData;
        expect(row).not.toBe('pendiente');
        expect(row.price).toBe(210.7);
        expect(row.marketCap).toBeNull();
        expect(row.metricsReadFailed).toBe(true);
        expect(marketCapGapReason({ ...row, timedOut: false })).toBe('readFailed');
    });
});
