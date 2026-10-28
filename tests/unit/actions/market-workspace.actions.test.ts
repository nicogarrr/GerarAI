import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
    requireAuthenticatedUser, researchIdentityHeaders,
    getCandles, getProfile, getStockQuote,
    datedQuoteMetrics, marketHistoryStatus, sessionDateEt, fetchDatedChanges,
    quoteSymbolFor, normalizeChartCandles, e2eMarketFixture, isE2EMarketFixtureEnabled,
} = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(async () => ({ id: 'user-1' })),
    researchIdentityHeaders: vi.fn<(...args: any[]) => any>(async () => ({ 'X-Tenant': 'user-1' })),
    getCandles: vi.fn<(...args: any[]) => any>(async () => ({ c: [], source: 'Finnhub', currency: 'USD' })),
    getProfile: vi.fn<(...args: any[]) => any>(async () => null),
    getStockQuote: vi.fn<(...args: any[]) => any>(async () => null),
    datedQuoteMetrics: vi.fn<(...args: any[]) => any>(() => ({ open: null, high: null, low: null, previousClose: null, source: null, timestamp: null })),
    marketHistoryStatus: vi.fn<(...args: any[]) => any>((n: number) => (n > 0 ? 'available' : 'unavailable')),
    sessionDateEt: vi.fn<(...args: any[]) => any>(() => '2026-10-27'),
    fetchDatedChanges: vi.fn<(...args: any[]) => any>(async () => ({})),
    quoteSymbolFor: vi.fn<(...args: any[]) => any>(),
    normalizeChartCandles: vi.fn<(...args: any[]) => any>(() => []),
    e2eMarketFixture: vi.fn<(...args: any[]) => any>(() => ({ ticker: 'E2E', status: 'available' })),
    isE2EMarketFixtureEnabled: vi.fn<(...args: any[]) => any>(() => false),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getCandles, getProfile, getStockQuote }));
vi.mock('@/lib/market/quote-metrics', () => ({ datedQuoteMetrics }));
vi.mock('@/lib/market/history-status', () => ({ marketHistoryStatus }));
vi.mock('@/lib/market/quote-freshness', () => ({ sessionDateEt }));
vi.mock('@/lib/market/dated-change', () => ({ fetchDatedChanges }));
vi.mock('@/lib/market/quote-symbol', () => ({ quoteSymbolFor }));
vi.mock('@/lib/market/normalize-chart', () => ({ normalizeChartCandles }));
vi.mock('@/lib/e2e-market-fixture', () => ({ e2eMarketFixture, isE2EMarketFixtureEnabled }));

import { getCompanyMarketSnapshot, getResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';

const fetchMock = vi.fn<(...args: any[]) => any>();
vi.stubGlobal('fetch', fetchMock);

beforeEach(() => {
    vi.resetAllMocks();
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
    researchIdentityHeaders.mockResolvedValue({ 'X-Tenant': 'user-1' });
    getCandles.mockResolvedValue({ c: [], source: 'Finnhub', currency: 'USD' });
    getProfile.mockResolvedValue(null);
    getStockQuote.mockResolvedValue(null);
    datedQuoteMetrics.mockReturnValue({ open: null, high: null, low: null, previousClose: null, source: null, timestamp: null });
    marketHistoryStatus.mockImplementation((n: number) => (n > 0 ? 'available' : 'unavailable'));
    fetchDatedChanges.mockResolvedValue({});
    normalizeChartCandles.mockReturnValue([]);
    isE2EMarketFixtureEnabled.mockReturnValue(false);
    delete process.env.FMP_BACKEND_URL;
});

describe('getResearchCompanyBasics', () => {
    it('sin FMP_BACKEND_URL -> null sin llamar', async () => {
        expect(await getResearchCompanyBasics('SAN.MC')).toBeNull();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('respuesta no-ok, no-objeto o red caída -> null (nunca lanza)', async () => {
        process.env.FMP_BACKEND_URL = 'http://backend';
        fetchMock.mockResolvedValue({ ok: false } as Response);
        expect(await getResearchCompanyBasics('SAN.MC')).toBeNull();
        fetchMock.mockResolvedValue({ ok: true, json: async () => 'texto' } as unknown as Response);
        expect(await getResearchCompanyBasics('SAN.MC')).toBeNull();
        fetchMock.mockRejectedValue(new Error('timeout'));
        expect(await getResearchCompanyBasics('SAN.MC')).toBeNull();
    });

    it('ok -> datos de la ficha research', async () => {
        process.env.FMP_BACKEND_URL = 'http://backend';
        fetchMock.mockResolvedValue({ ok: true, json: async () => ({ ticker: 'SAN', name: 'Banco Santander', currency: 'EUR' }) } as Response);
        expect(await getResearchCompanyBasics('SAN.MC')).toMatchObject({ name: 'Banco Santander' });
    });
});

describe('getCompanyMarketSnapshot', () => {
    it('sin identidad de listado verificada -> unavailable, NUNCA cotiza el ticker desnudo', async () => {
        quoteSymbolFor.mockReturnValue(null);
        const snap = await getCompanyMarketSnapshot('alm.mc');
        expect(snap.status).toBe('unavailable');
        expect(snap.quote.price).toBeNull();
        expect(snap.quote.priceKind).toBeNull();
        expect(getStockQuote).not.toHaveBeenCalled();
    });

    it('cotización viva -> priceKind live, priceAsOf null, sin dated changes', async () => {
        quoteSymbolFor.mockReturnValue('SAN.MC');
        getStockQuote.mockResolvedValue({ c: 4.5, d: 0.1, dp: 2.2, t: 1777000000, kind: 'live' });
        const snap = await getCompanyMarketSnapshot('SAN.MC');
        expect(snap.quote).toMatchObject({ price: 4.5, change: 0.1, changePercent: 2.2, priceKind: 'live', priceAsOf: null });
        expect(fetchDatedChanges).not.toHaveBeenCalled();
    });

    it('fuera de sesión -> cierre datado de /api/market/changes con su fecha y divisa', async () => {
        quoteSymbolFor.mockReturnValue('CGEO.L');
        getStockQuote.mockResolvedValue({ c: 3.2, d: -0.05, dp: -1.5, t: 1777000000, kind: 'close' });
        fetchDatedChanges.mockResolvedValue({ 'CGEO.L': { price: 3.18, change: -0.02, changePercent: -0.82, previousClose: 3.2, currency: 'GBp', date: '2026-10-16' } });
        const snap = await getCompanyMarketSnapshot('CGEO.L');
        expect(snap.quote).toMatchObject({ price: 3.18, changePercent: -0.82, priceKind: 'close', priceAsOf: '2026-10-16' });
        expect(snap.currency).toBe('GBp'); // la divisa del dato datado, no la del perfil
    });

    it('sin cotización usable -> último cierre de vela CON su fecha; sin velas -> null', async () => {
        quoteSymbolFor.mockReturnValue('AAPL');
        getStockQuote.mockResolvedValue(null); // proveedor caído
        normalizeChartCandles.mockReturnValue([{ date: '2026-10-26', close: 150 }, { date: '2026-10-27', close: 152 }]);
        const snap = await getCompanyMarketSnapshot('AAPL');
        expect(snap.quote).toMatchObject({ price: 152, priceKind: 'close', priceAsOf: '2026-10-27', change: null, changePercent: null });
    });

    it('cotización sin frescura validada (kind desconocido) no se pinta como precio actual', async () => {
        quoteSymbolFor.mockReturnValue('AAPL');
        getStockQuote.mockResolvedValue({ c: 150, d: 1, dp: 0.7, t: null, kind: undefined });
        const snap = await getCompanyMarketSnapshot('AAPL');
        expect(snap.quote.price).toBeNull(); // sin dated, sin velas -> null
        expect(snap.quote.priceKind).toBeNull();
    });

    it('el nombre lo pone el master; el perfil del proveedor solo rellena huecos', async () => {
        quoteSymbolFor.mockReturnValue('SAN.MC');
        process.env.FMP_BACKEND_URL = 'http://backend';
        fetchMock.mockResolvedValue({ ok: true, json: async () => ({ ticker: 'SAN', name: 'Banco Santander', exchange: 'BME', currency: 'EUR' }) } as Response);
        getProfile.mockResolvedValue({ name: 'SANTANDER US TWIN', exchange: 'NYSE', currency: 'USD' });
        getStockQuote.mockResolvedValue({ c: 4.5, kind: 'live', t: 1 });
        const snap = await getCompanyMarketSnapshot('SAN.MC');
        expect(snap.name).toBe('Banco Santander'); // nunca el gemelo americano
        expect(snap.exchange).toBe('BME');
        expect(snap.currency).toBe('EUR');
    });

    it('sin velas el status es «no disponible» aunque la cotización cargue (F161)', async () => {
        quoteSymbolFor.mockReturnValue('AAPL');
        getStockQuote.mockResolvedValue({ c: 150, kind: 'live', t: 1 });
        const snap = await getCompanyMarketSnapshot('AAPL');
        expect(marketHistoryStatus).toHaveBeenCalledWith(0);
        expect(snap.status).toBe('unavailable');
    });

    it('historyCurrency null si el proveedor no la declara', async () => {
        quoteSymbolFor.mockReturnValue('AAPL');
        getCandles.mockResolvedValue({ c: [], source: 'Finnhub', currency: '  ' });
        const snap = await getCompanyMarketSnapshot('AAPL');
        expect(snap.historyCurrency).toBeNull();
    });

    it('fixture E2E activo -> devuelve el fixture sin tocar proveedores', async () => {
        isE2EMarketFixtureEnabled.mockReturnValue(true);
        const snap = await getCompanyMarketSnapshot('E2E');
        expect(snap.ticker).toBe('E2E');
        expect(getStockQuote).not.toHaveBeenCalled();
    });
});
