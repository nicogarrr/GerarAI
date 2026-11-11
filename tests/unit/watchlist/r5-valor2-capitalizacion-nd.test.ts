import { beforeEach, describe, expect, it, vi } from 'vitest';

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

import { getWatchlistEntryData } from '@/lib/actions/watchlist.actions';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import { marketCapGapReason } from '@/lib/watchlist/market-cap-gap';
import { peNdNote } from '@/lib/watchlist/pe-nd-reason';

const BACKEND_CAP = { market_cap: 154_990_000_000, per: 29.8, currency: 'EUR', sources: ['Capitalización: yahoo', 'PER: cierre / eps_diluted FY2025 (ESEF)'] };

beforeEach(() => {
    vi.clearAllMocks();
    getStockQuote.mockResolvedValue(null);
    researchRequest.mockResolvedValue(BACKEND_CAP);
});

/**
 * r5-front (11-nov-2026, AUDIT #5): AIR.PA (bolsa «EPA») y FFH.TO («TSX») salían
 * «Capitalización N/D: la fuente no facilita una capitalización verificable»
 * aunque /api/watchlist/metrics devolvía 154.990 M €. Causa: esas plazas no
 * estaban en el mapa de sufijos, sin línea de cotización la entrada se devolvía
 * vacía SIN pedir al backend sus propias cifras (que no dependen de la
 * cotización) y la leyenda decía «no facilita». Además cualquier fallo de la
 * lectura (timeout, 5xx) se tragaba como «sin dato».
 */
describe('plazas con código corto: EPA (París) y TSX (Toronto)', () => {
    it('EPA cotiza con .PA y TSX con .TO (verificado contra Yahoo chart: AIR.PA PAR/EUR, FFH.TO TOR/CAD)', () => {
        expect(quoteSymbolFor({ exchange: 'EPA', currency: 'EUR' }, 'AIR.PA')).toBe('AIR.PA');
        expect(quoteSymbolFor({ exchange: 'EPA', currency: 'EUR' }, 'BVI')).toBe('BVI.PA');
        expect(quoteSymbolFor({ exchange: 'TSX', currency: 'CAD' }, 'FFH.TO')).toBe('FFH.TO');
    });

    it('AIR.PA enseña la capitalización del backend', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'AIR.PA', name: 'Airbus SE', exchange: 'EPA', currency: 'EUR' });
        const entry = await getWatchlistEntryData('AIR.PA');
        expect(entry.marketCap).toBe(154_990_000_000);
        expect(entry.peRatio).toBe(29.8);
        expect(entry.metricsNotApplicable).toBe(true);
    });
});

describe('sin línea de cotización validada: las cifras propias del backend siguen valiendo', () => {
    it('una plaza no-US sin sufijo conocido conserva cap y PER del backend (sin precio)', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'PKN', name: 'Orlen', exchange: 'WARSAW STOCK EXCHANGE', currency: 'PLN' });
        const entry = await getWatchlistEntryData('PKN');
        expect(entry.quoteSymbol).toBeNull();
        expect(entry.price).toBeNull();
        expect(getStockQuote).not.toHaveBeenCalled();
        expect(getStockValuationBasics).not.toHaveBeenCalled();
        expect(entry.marketCap).toBe(154_990_000_000);
        expect(entry.metricsNotApplicable).toBe(true);
        expect(marketCapGapReason({ ...entry, timedOut: false })).toBeNull();
    });

    it('sin master (empresa desconocida) no se pide nada al backend', async () => {
        getResearchCompanyBasics.mockResolvedValue(null);
        const entry = await getWatchlistEntryData('ZZZZ');
        expect(researchRequest).not.toHaveBeenCalled();
        expect(entry.marketCap).toBeNull();
    });
});

describe('lectura fallida ≠ la fuente no lo da', () => {
    it('si /metrics falla (timeout o error), la capitalización N/D dice que no se pudo leer', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'AIR.PA', name: 'Airbus SE', exchange: 'EPA', currency: 'EUR' });
        researchRequest.mockRejectedValue(new Error('Research engine unavailable for /api/watchlist/metrics/AIR.PA (timeout de 15000 ms)'));
        const entry = await getWatchlistEntryData('AIR.PA');
        expect(entry.marketCap).toBeNull();
        expect(entry.metricsReadFailed).toBe(true);
        expect(marketCapGapReason({ ...entry, timedOut: false })).toBe('readFailed');
        // El PER tampoco dice «la fuente no cubre»: no se pudo leer.
        expect(peNdNote({ ...entry, timedOut: false })).toEqual({ key: 'watchlist.page.readFailed' });
    });

    it('si /metrics responde sin cap, se mantiene el motivo de ausencia', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'AIR.PA', name: 'Airbus SE', exchange: 'EPA', currency: 'EUR' });
        researchRequest.mockResolvedValue({ market_cap: null, per: null, currency: 'EUR', sources: [] });
        const entry = await getWatchlistEntryData('AIR.PA');
        expect(entry.metricsReadFailed).toBe(false);
        expect(marketCapGapReason({ ...entry, timedOut: false })).toBe('notApplicable');
    });

    it('una línea US con Finnhub y respaldo caídos tampoco se rotula «no facilita»', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'AAPL', name: 'Apple', exchange: 'NASDAQ', currency: 'USD' });
        getStockValuationBasics.mockResolvedValue(null);
        researchRequest.mockRejectedValue(new Error('500 Internal Server Error'));
        const entry = await getWatchlistEntryData('AAPL');
        expect(marketCapGapReason({ ...entry, timedOut: false })).toBe('readFailed');
    });

    it('orden de motivos: presupuesto agotado manda; con cap no hay motivo', () => {
        const base = { marketCap: null, metricsNotApplicable: false, metricsReadFailed: false, timedOut: false };
        expect(marketCapGapReason({ ...base, timedOut: true, metricsReadFailed: true })).toBe('timedOut');
        expect(marketCapGapReason(base)).toBe('unverifiable');
        expect(marketCapGapReason({ ...base, marketCap: 1 })).toBeNull();
    });
});
