import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, fetchJSON, researchIdentityHeaders, getNewsWithFallback } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(),
    fetchJSON: vi.fn(),
    researchIdentityHeaders: vi.fn(),
    getNewsWithFallback: vi.fn(),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/upstream/finnhub', () => ({ fetchJSON }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders }));
vi.mock('@/lib/cache/memoryTTL', () => ({ cachedFetch: (_k: string, fetcher: () => Promise<unknown>) => fetcher() }));
vi.mock('@/lib/actions/newsSources.actions', () => ({ getNewsWithFallback }));

const loadModule = async (apiKey?: string) => {
    vi.resetModules();
    if (apiKey === undefined) delete process.env.FINNHUB_API_KEY;
    else process.env.FINNHUB_API_KEY = apiKey;
    return import('@/lib/actions/finnhub.actions');
};

const freshT = () => Math.floor(Date.now() / 1000);

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'log').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    researchIdentityHeaders.mockResolvedValue({});
});

afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.FINNHUB_API_KEY;
    delete process.env.FMP_BACKEND_URL;
});

describe('getCandles', () => {
    it('Finnhub OK -> velas con source Finnhub', async () => {
        const { getCandles } = await loadModule('key');
        fetchJSON.mockResolvedValue({ s: 'ok', c: [1, 2], t: [1, 2], o: [], h: [], l: [], v: [] });
        const result = await getCandles('AAPL', 1, 2);
        expect(result.source).toBe('Finnhub');
        expect(result.c).toEqual([1, 2]);
        expect(fetchJSON.mock.calls[0][0]).toContain('/stock/candle?symbol=AAPL');
    });

    it('Finnhub sin datos y backend Yahoo OK -> fallback con su fuente', async () => {
        const { getCandles } = await loadModule('key');
        fetchJSON.mockResolvedValue([]);
        process.env.FMP_BACKEND_URL = 'https://backend.example';
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true,
            json: async () => ({ s: 'ok', c: [3], t: [3], o: [], h: [], l: [], v: [], source: 'Yahoo Finance' }),
        })));
        const result = await getCandles('SAN.MC', 1, 2);
        expect(result.source).toBe('Yahoo Finance');
        expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/api/market/candles/SAN.MC?from=1&to=2&resolution=D');
    });

    it('todo caído -> no_data vacío, nunca velas inventadas', async () => {
        const { getCandles } = await loadModule(undefined);
        const result = await getCandles('AAPL', 1, 2);
        expect(result).toEqual({ s: 'no_data', c: [], t: [], o: [], h: [], l: [], v: [] });
    });
});

describe('getProfile', () => {
    it('devuelve el perfil; una respuesta rara (array) es null', async () => {
        const { getProfile } = await loadModule('key');
        fetchJSON.mockResolvedValue({ ticker: 'AAPL', name: 'Apple' });
        expect(await getProfile('aapl')).toMatchObject({ name: 'Apple' });
        fetchJSON.mockResolvedValue([]);
        expect(await getProfile('AAPL')).toBeNull();
    });

    it('sin clave -> null sin llamar', async () => {
        const { getProfile } = await loadModule(undefined);
        expect(await getProfile('AAPL')).toBeNull();
        expect(fetchJSON).not.toHaveBeenCalled();
    });
});

describe('getNews', () => {
    it('multi-fuente con resultados -> se usan tal cual', async () => {
        const { getNews } = await loadModule('key');
        getNewsWithFallback.mockResolvedValue([{ id: 1, headline: 'h' }]);
        expect(await getNews(['AAPL'])).toEqual([{ id: 1, headline: 'h' }]);
        expect(fetchJSON).not.toHaveBeenCalled();
    });

    it('multi-fuente vacío -> fallback Finnhub por empresa con round-robin y orden por fecha', async () => {
        const { getNews } = await loadModule('key');
        getNewsWithFallback.mockResolvedValue([]);
        const article = (headline: string, datetime: number) => ({ headline, summary: 's', url: `https://x/${headline}`, datetime });
        fetchJSON.mockImplementation(async (url: string) => {
            if (url.includes('symbol=AAPL')) return [article('a1', 100), article('a2', 300)];
            if (url.includes('symbol=MSFT')) return [article('m1', 200)];
            return [];
        });
        const news = await getNews(['AAPL', 'MSFT']);
        expect(news.map((n) => n.headline)).toEqual(['a2', 'm1', 'a1']);
        expect(news.every((n) => n.category === 'company')).toBe(true);
    });

    it('sin noticias de empresa cae al general filtrando relevancia financiera y duplicados', async () => {
        const { getNews } = await loadModule('key');
        getNewsWithFallback.mockResolvedValue([]);
        fetchJSON.mockImplementation(async (url: string) => {
            if (url.includes('company-news')) return [];
            return [
                { id: 1, headline: 'Stocks rally', summary: 's', url: 'https://x/1', datetime: 5 },
                { id: 1, headline: 'Stocks rally', summary: 's', url: 'https://x/1', datetime: 5 },
                { id: 2, headline: 'Receta de cocina para niños', summary: 'pure crianza toddler parenting', url: 'https://x/2', datetime: 6 },
            ];
        });
        const news = await getNews(['AAPL']);
        expect(news).toHaveLength(1);
        expect(news[0].headline).toBe('Stocks rally');
        expect(news[0].category).toBe('general');
    });

    it('sin FINNHUB_API_KEY y sin noticias multi-fuente -> lista vacía, sin error ni console.error', async () => {
        const { getNews } = await loadModule();
        getNewsWithFallback.mockResolvedValue([]);
        await expect(getNews(['AAPL'])).resolves.toEqual([]);
        expect(fetchJSON).not.toHaveBeenCalled();
        expect(console.error).not.toHaveBeenCalled();
    });

    it('error total -> lanza "Failed to fetch news"', async () => {
        const { getNews } = await loadModule('key');
        getNewsWithFallback.mockRejectedValue(new Error('todo caído'));
        await expect(getNews(['AAPL'])).rejects.toThrow('Failed to fetch news');
    });
});

describe('getStockValuationBasics vs getStockFinancialDataLight', () => {
    it('basics NO pide /quote ni /price-target (cuota del plan free)', async () => {
        const { getStockValuationBasics } = await loadModule('key');
        fetchJSON.mockResolvedValue({ metric: {} });
        const result = await getStockValuationBasics('AAPL');
        const urls = fetchJSON.mock.calls.map((c) => String(c[0]));
        expect(urls.some((u) => u.includes('/quote?'))).toBe(false);
        expect(urls.some((u) => u.includes('price-target'))).toBe(false);
        expect(urls.some((u) => u.includes('profile2'))).toBe(true);
        expect(urls.some((u) => u.includes('metric'))).toBe(true);
        expect(result).toEqual({ profile: { metric: {} }, metrics: { metric: {} } });
    });

    it('light: cotización rancia (timestamp viejo) se rechaza -> quote null', async () => {
        const { getStockFinancialDataLight } = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            if (url.includes('/quote?')) return { c: 150, t: 946684800 }; // año 2000: stale
            if (url.includes('profile2')) return { name: 'Apple' };
            if (url.includes('price-target')) return { targetMean: 200 };
            return { metric: {} };
        });
        const result = await getStockFinancialDataLight('AAPL');
        expect(result?.quote).toBeNull();
        expect(result?.profile).toEqual({ name: 'Apple' });
        expect(result?.priceTarget).toEqual({ targetMean: 200 });
    });

    it('sin clave -> null', async () => {
        const { getStockFinancialDataLight, getStockValuationBasics } = await loadModule(undefined);
        expect(await getStockFinancialDataLight('AAPL')).toBeNull();
        expect(await getStockValuationBasics('AAPL')).toBeNull();
    });
});

describe('searchStocksWithStatus', () => {
    it('entrada no soportada (>120 chars o control) -> ok vacío sin llamar al proveedor', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        expect(await searchStocksWithStatus('x'.repeat(121))).toEqual({ status: 'ok', stocks: [] });
        expect(await searchStocksWithStatus('a<b')).toEqual({ status: 'ok', stocks: [] });
        expect(fetchJSON).not.toHaveBeenCalled();
    });

    it('mapea resultados, deduplica símbolo y deriva la bolsa del sufijo (300183.SZ no es "US")', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockResolvedValue({
            result: [
                { symbol: 'AENA.MC', displaySymbol: 'AENA.MC', description: 'Aena', type: 'Common Stock' },
                { symbol: 'AENA.MC', displaySymbol: 'AENA.MC', description: 'Aena duplicada', type: 'Common Stock' },
                { symbol: '300183.SZ', displaySymbol: '300183.SZ', description: 'Shenzhen Co', type: 'Common Stock' },
            ],
        });
        const result = await searchStocksWithStatus('aena');
        expect(result.status).toBe('ok');
        const symbols = result.stocks.map((s) => s.symbol);
        expect(symbols.filter((s) => s === 'AENA.MC')).toHaveLength(1);
        expect(result.stocks.find((s) => s.symbol === '300183.SZ')?.exchange).not.toBe('US');
    });

    it('ticker con punto sin match exacto: fallback por la base y exacto primero', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            const q = new URL(url).searchParams.get('q');
            if (q === 'SAN.MC') return { result: [{ symbol: 'SAN', displaySymbol: 'SAN', description: 'Sin punto' }] };
            if (q === 'SAN') return { result: [{ symbol: 'SAN.MC', displaySymbol: 'SAN.MC', description: 'Banco Santander' }] };
            return { result: [] };
        });
        const result = await searchStocksWithStatus('SAN.MC');
        expect(result.stocks[0]?.symbol).toBe('SAN.MC');
        expect(fetchJSON).toHaveBeenCalledTimes(2);
    });

    it('fallo total del proveedor sin cobertura local -> status error (la UI no miente con "sin resultados")', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockRejectedValue(new Error('429'));
        const result = await searchStocksWithStatus('zzqnotastock');
        expect(result).toEqual({ status: 'error', stocks: [] });
    });
});

describe('getPopularStocks', () => {
    it('sin clave -> ok con lista vacía (Finnhub opcional)', async () => {
        const { getPopularStocks } = await loadModule(undefined);
        expect(await getPopularStocks()).toEqual({ status: 'ok', stocks: [] });
    });

    it('0/10 perfiles con clave -> error (proveedor caído, no "no hay acciones")', async () => {
        const { getPopularStocks } = await loadModule('key');
        fetchJSON.mockRejectedValue(new Error('429'));
        expect(await getPopularStocks()).toEqual({ status: 'error' });
    });

    it('perfiles OK -> normaliza la etiqueta de bolsa', async () => {
        const { getPopularStocks } = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) =>
            url.includes('AAPL') ? { name: 'Apple', exchange: 'NASDAQ NMS - GLOBAL MARKET' } : { name: 'X', exchange: 'NEW YORK STOCK EXCHANGE, INC.' });
        const result = await getPopularStocks();
        expect(result.status).toBe('ok');
        if (result.status === 'ok') {
            expect(result.stocks.find((s) => s.symbol === 'AAPL')?.exchange).toBe('NASDAQ');
            expect(result.stocks[1]?.exchange).toBe('NYSE');
        }
    });
});

describe('getStockQuote', () => {
    it('cotización fresca -> se devuelve con su kind', async () => {
        const { getStockQuote } = await loadModule('key');
        fetchJSON.mockResolvedValue({ c: 150, d: 1, dp: 0.7, h: 151, l: 149, o: 150, pc: 149, t: freshT() });
        const quote = await getStockQuote('AAPL');
        expect(quote).toMatchObject({ c: 150, source: 'Finnhub' });
        expect(['live', 'close']).toContain(quote?.kind);
    });

    it('rancia en Finnhub -> fallback Yahoo con closeDate exacto de la vela', async () => {
        const { getStockQuote } = await loadModule('key');
        fetchJSON.mockResolvedValue({ c: 150, t: 946684800 });
        process.env.FMP_BACKEND_URL = 'https://backend.example';
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true,
            json: async () => ({ c: 99, pc: 98, cd: '2026-10-27' }),
        })));
        const quote = await getStockQuote('SAN.MC');
        expect(quote).toMatchObject({ c: 99, source: 'Yahoo Finance', kind: 'close', closeDate: '2026-10-27', t: null });
    });

    it('todo caído -> null (la UI rotula desconocido, no inventa)', async () => {
        const { getStockQuote } = await loadModule(undefined);
        expect(await getStockQuote('AAPL')).toBeNull();
    });
});
