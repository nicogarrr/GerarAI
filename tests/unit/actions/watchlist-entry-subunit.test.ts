import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, getResearchCompanyBasics, getStockQuote, getStockValuationBasics } = vi.hoisted(() => ({
    researchRequest: vi.fn<(...args: any[]) => any>(),
    getResearchCompanyBasics: vi.fn<(...args: any[]) => any>(),
    getStockQuote: vi.fn<(...args: any[]) => any>(),
    getStockValuationBasics: vi.fn<(...args: any[]) => any>(async () => null),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: async () => ({ id: 'user-1' }) }));
vi.mock('@/lib/actions/market-workspace.actions', () => ({ getResearchCompanyBasics }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getStockQuote, getStockValuationBasics }));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));

import { getWatchlistEntryData } from '@/lib/actions/watchlist.actions';
import { mapBackendYahooQuote } from '@/lib/market/quote-freshness';

beforeEach(() => {
    vi.clearAllMocks();
    researchRequest.mockResolvedValue({ market_cap: null, per: null, currency: 'GBP', sources: [] });
});

/**
 * E2E (user-flows/watchlist, 28-oct-2026): VOD.L salía «118,25 GBP» en la
 * watchlist. Yahoo cotiza Londres en peniques (GBp: 118,25 p = 1,1825 £) y la
 * fila lo rotulaba con la divisa del master (GBP): precio ×100.
 */
describe('watchlist: cotización en subunidad (peniques)', () => {
    it('el cierre Yahoo del backend conserva su unidad (GBp)', () => {
        const q = mapBackendYahooQuote({ c: 118.25, d: 0.05, dp: 0.0423, pc: 118.2, currency: 'GBp', cd: '2026-10-26' } as never);
        expect(q?.currency).toBe('GBp');
    });

    it('un .L en GBp con master GBP se muestra en libras (÷100), no 118,25 GBP', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'VOD.L', name: 'Vodafone Group', exchange: 'LSE', currency: 'GBP' });
        getStockQuote.mockResolvedValue({ source: 'Yahoo Finance', c: 118.25, d: 0.05, dp: 0.0423, h: 0, l: 0, o: 0, pc: 118.2, t: null, kind: 'close', closeDate: '2026-10-26', currency: 'GBp' });
        const entry = await getWatchlistEntryData('VOD.L');
        expect(entry.currency).toBe('GBP');
        expect(entry.price).toBeCloseTo(1.1825, 6);
        expect(entry.change).toBeCloseTo(0.0005, 6);
        expect(entry.changePercent).toBeCloseTo(0.0423, 6); // el % no cambia con la unidad
        expect(entry.priceAsOf).toBe('2026-10-26');
    });

    it('sin divisa del master, la unidad mayor de la cotización rotula el precio', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'CGEO.L', name: 'Georgia Capital', exchange: 'LSE', currency: '' });
        researchRequest.mockResolvedValue(null);
        getStockQuote.mockResolvedValue({ source: 'Yahoo Finance', c: 1500, d: null, dp: null, h: 0, l: 0, o: 0, pc: 0, t: null, kind: 'close', closeDate: '2026-10-26', currency: 'GBX' });
        const entry = await getWatchlistEntryData('CGEO.L');
        expect(entry.currency).toBe('GBP');
        expect(entry.price).toBeCloseTo(15, 6);
        expect(entry.change).toBeNull();
    });

    it('una cotización en unidad mayor no se toca (MC.PA en EUR, AAPL sin divisa declarada)', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'SAP', name: 'SAP', exchange: 'XETRA', currency: 'EUR' });
        getStockQuote.mockResolvedValue({ source: 'Yahoo Finance', c: 385.4, d: 2.4, dp: 0.63, h: 0, l: 0, o: 0, pc: 383, t: null, kind: 'close', closeDate: '2026-10-26', currency: 'EUR' });
        const eur = await getWatchlistEntryData('SAP');
        expect(eur).toMatchObject({ price: 385.4, change: 2.4, currency: 'EUR' });

        getResearchCompanyBasics.mockResolvedValue({ ticker: 'AAPL', name: 'Apple', exchange: 'NASDAQ', currency: 'USD' });
        getStockQuote.mockResolvedValue({ source: 'Finnhub', c: 180, d: 1, dp: 0.5, h: 0, l: 0, o: 0, pc: 179, t: Math.floor(Date.now() / 1000), kind: 'live' });
        const usd = await getWatchlistEntryData('AAPL');
        expect(usd).toMatchObject({ price: 180, change: 1, currency: 'USD' });
    });
});

describe('watchlist: etiqueta visible de la fuente del PER', () => {
    it('PER TTM de Finnhub se etiqueta «Finnhub»', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'GOOGL', name: 'Alphabet', exchange: 'NASDAQ', currency: 'USD' });
        getStockQuote.mockResolvedValue({ source: 'Finnhub', c: 279.84, d: 1, dp: 0.4, h: 0, l: 0, o: 0, pc: 278, t: Math.floor(Date.now() / 1000), kind: 'live' });
        getStockValuationBasics.mockResolvedValue({ metrics: { metric: { peTTM: 14.5 } } });
        const entry = await getWatchlistEntryData('GOOGL');
        expect(entry.peRatio).toBe(14.5);
        expect(entry.peKind).toBe('ttm');
        expect(entry.peSourceLabel).toBe('Finnhub');
    });

    it('PER de respaldo del backend se etiqueta con la fuente entre paréntesis', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'GOOGL', name: 'Alphabet', exchange: 'NASDAQ', currency: 'USD' });
        getStockQuote.mockResolvedValue({ source: 'Finnhub', c: 279.84, d: 1, dp: 0.4, h: 0, l: 0, o: 0, pc: 278, t: Math.floor(Date.now() / 1000), kind: 'live' });
        getStockValuationBasics.mockResolvedValue({ metrics: { metric: {} } });
        researchRequest.mockResolvedValue({ market_cap: null, per: 13.66, currency: 'USD', sources: ['PER: cierre 2026-10-30 / EPS diluido FY2025 (SEC)'] });
        const entry = await getWatchlistEntryData('GOOGL');
        expect(entry.peRatio).toBe(13.66);
        expect(entry.peKind).toBe('fy');
        expect(entry.peSourceLabel).toBe('SEC');
    });

    it('sin fuente entre paréntesis no se inventa la etiqueta', async () => {
        getResearchCompanyBasics.mockResolvedValue({ ticker: 'GOOGL', name: 'Alphabet', exchange: 'NASDAQ', currency: 'USD' });
        getStockQuote.mockResolvedValue({ source: 'Finnhub', c: 279.84, d: 1, dp: 0.4, h: 0, l: 0, o: 0, pc: 278, t: Math.floor(Date.now() / 1000), kind: 'live' });
        getStockValuationBasics.mockResolvedValue({ metrics: { metric: {} } });
        researchRequest.mockResolvedValue({ market_cap: null, per: 13.66, currency: 'USD', sources: ['PER: cierre 2026-10-30 / EPS FY2025'] });
        const entry = await getWatchlistEntryData('GOOGL');
        expect(entry.peRatio).toBe(13.66);
        expect(entry.peSourceLabel).toBeNull();
    });
});
