import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, fetchJSON, researchIdentityHeaders, getNewsWithFallback, searchSecUniverse } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(),
    fetchJSON: vi.fn(),
    researchIdentityHeaders: vi.fn(),
    getNewsWithFallback: vi.fn(),
    searchSecUniverse: vi.fn(),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/upstream/finnhub', () => ({ fetchJSON }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders }));
vi.mock('@/lib/market/sec-universe-search', () => ({ searchSecUniverse }));
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
    searchSecUniverse.mockResolvedValue([]);
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

    it('cero resultados en todas las fuentes pero la SEC conoce la empresa -> ok con la candidata oficial', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockResolvedValue({ result: [] });
        searchSecUniverse.mockResolvedValue([
            { symbol: 'ANT', name: 'Anthropic, PBC', exchange: 'US', type: 'Stock', isInWatchlist: false },
        ]);
        const result = await searchStocksWithStatus('Antrophic');
        expect(searchSecUniverse).toHaveBeenCalledWith('Antrophic');
        expect(result.status).toBe('ok');
        expect(result.stocks.map((s) => s.symbol)).toEqual(['ANT']);
    });

    it('con resultados del proveedor la SEC NO se consulta (última instancia, nunca desplaza)', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockResolvedValue({
            result: [{ symbol: 'AAPL', displaySymbol: 'AAPL', description: 'Apple', type: 'Common Stock' }],
        });
        const result = await searchStocksWithStatus('apple');
        expect(result.stocks[0]?.symbol).toBe('AAPL');
        expect(searchSecUniverse).not.toHaveBeenCalled();
    });

    it('proveedor caído y la SEC con candidata -> ok con la candidata (mejor que un error a secas)', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockRejectedValue(new Error('429'));
        searchSecUniverse.mockResolvedValue([
            { symbol: 'ANT', name: 'Anthropic, PBC', exchange: 'US', type: 'Stock', isInWatchlist: false },
        ]);
        const result = await searchStocksWithStatus('Antrophic');
        expect(result.status).toBe('ok');
        expect(result.stocks[0]?.symbol).toBe('ANT');
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

describe('cobertura de ramas de búsqueda y respaldos (Auditor #6018)', () => {
    it('sin clave Finnhub la búsqueda devuelve ok vacío (proveedor opcional)', async () => {
        const { searchStocksWithStatus } = await loadModule(undefined);
        expect(await searchStocksWithStatus('anthropic')).toEqual({ status: 'ok', stocks: [] });
        expect(fetchJSON).not.toHaveBeenCalled();
    });

    it('consulta vacía -> populares; si los perfiles fallan todos -> error honesto', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockResolvedValue({ ticker: 'AAPL', name: 'Apple', exchange: 'NASDAQ' });
        const ok = await searchStocksWithStatus('');
        expect(ok.status).toBe('ok');
        expect(ok.stocks.length).toBeGreaterThan(0);

        const again = await loadModule('key');
        fetchJSON.mockRejectedValue(new Error('down'));
        expect(await again.searchStocksWithStatus('')).toEqual({ status: 'error', stocks: [] });
    });

    it('respuesta de búsqueda sin array result -> lista vacía, no excepción', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockResolvedValue({});
        const result = await searchStocksWithStatus('zzqnotastock');
        expect(result).toEqual({ status: 'ok', stocks: [] });
    });

    it('ticker con punto: la búsqueda de la base falla -> conserva lo que hubiera', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            const q = new URL(url).searchParams.get('q');
            if (q === 'XYZ.MC') return { result: [{ symbol: 'XYZ', displaySymbol: 'XYZ', description: 'Sin punto' }] };
            throw new Error('429');
        });
        const result = await searchStocksWithStatus('XYZ.MC');
        expect(result.status).toBe('ok');
        expect(result.stocks.map((s) => s.symbol)).toEqual(['XYZ']);
    });

    it('ticker con punto: la base no devuelve el exacto -> no antepone nada', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            const q = new URL(url).searchParams.get('q');
            if (q === 'XYZ.MC') return { result: [] };
            if (q === 'XYZ') return { result: [{ symbol: 'XYZ', displaySymbol: 'XYZ', description: 'Otra' }] };
            return { result: [] };
        });
        const result = await searchStocksWithStatus('XYZ.MC');
        expect(result.stocks).toEqual([]);
    });

    it('prefijo tipo AMZ: enriquece con el listado US del mismo nombre; si falla, conserva', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            const q = new URL(url).searchParams.get('q');
            if (q === 'AMZ') return { result: [{ symbol: 'AMZ.DE', displaySymbol: 'AMZ.DE', description: 'Amazon', type: 'Common Stock' }] };
            if (q === 'Amazon') return { result: [{ symbol: 'AMZN', displaySymbol: 'AMZN', description: 'Amazon', type: 'Common Stock' }] };
            return { result: [] };
        });
        const result = await searchStocksWithStatus('AMZ');
        expect(result.stocks[0]?.symbol).toBe('AMZN');

        const again = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            const q = new URL(url).searchParams.get('q');
            if (q === 'AMZ') return { result: [{ symbol: 'AMZ.DE', displaySymbol: 'AMZ.DE', description: 'Amazon', type: 'Common Stock' }] };
            throw new Error('down');
        });
        const degraded = await again.searchStocksWithStatus('AMZ');
        expect(degraded.status).toBe('ok');
        expect(degraded.stocks.map((s) => s.symbol)).toEqual(['AMZ.DE']);
    });

    it('ticker desnudo sin match: perfil exacto por símbolo; sin perfil o con error, no inventa', async () => {
        const { searchStocksWithStatus } = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            if (url.includes('/stock/profile2')) return { name: 'AST SpaceMobile' };
            return { result: [] };
        });
        const result = await searchStocksWithStatus('ASTS');
        expect(result.stocks[0]?.symbol).toBe('ASTS');
        expect(result.stocks[0]?.name).toBe('AST SpaceMobile');

        const noProfile = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            if (url.includes('/stock/profile2')) return [];
            return { result: [] };
        });
        expect((await noProfile.searchStocksWithStatus('ASTS')).stocks).toEqual([]);

        const downProfile = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            if (url.includes('/stock/profile2')) throw new Error('down');
            return { result: [] };
        });
        expect((await downProfile.searchStocksWithStatus('ASTS')).stocks).toEqual([]);
    });

    it('master propio: mapea filas válidas, descarta incompletas y bolsa desconocida -> vacío', async () => {
        const { searchStocksWithStatus } = await loadModule(undefined);
        process.env.FMP_BACKEND_URL = 'https://backend.example';
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true,
            json: async () => ({
                results: [
                    { ticker: 'AAA', name: 'AAA Co', exchange: '' },
                    { ticker: '', name: 'Sin ticker' },
                    { ticker: 'BBB' },
                    'no-es-objeto',
                ],
            }),
        })));
        const result = await searchStocksWithStatus('AAA');
        expect(result.stocks.map((s) => s.symbol)).toEqual(['AAA']);
        expect(result.stocks[0]?.exchange).toBe('');
    });

    it('master propio: respuesta no OK o fetch roto -> sigue por Finnhub sin master', async () => {
        const mod = await loadModule('key');
        process.env.FMP_BACKEND_URL = 'https://backend.example';
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })));
        fetchJSON.mockResolvedValue({ result: [{ symbol: 'AAPL', displaySymbol: 'AAPL', description: 'Apple', type: 'Common Stock' }] });
        expect((await mod.searchStocksWithStatus('apple')).stocks[0]?.symbol).toBe('AAPL');

        const broken = await loadModule('key');
        process.env.FMP_BACKEND_URL = 'https://backend.example';
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network'); }));
        fetchJSON.mockResolvedValue({ result: [{ symbol: 'AAPL', displaySymbol: 'AAPL', description: 'Apple', type: 'Common Stock' }] });
        expect((await broken.searchStocksWithStatus('apple')).stocks[0]?.symbol).toBe('AAPL');
    });

    it('getCandles: primer intento del backend KO, el reintento sirve velas; y luego la caché stale cubre un apagón', async () => {
        vi.useFakeTimers();
        try {
            vi.setSystemTime(new Date('2026-11-19T10:00:00Z'));
            const { getCandles } = await loadModule('key');
            fetchJSON.mockRejectedValue(new Error('403'));
            process.env.FMP_BACKEND_URL = 'https://backend.example';
            let calls = 0;
            vi.stubGlobal('fetch', vi.fn(async () => {
                calls += 1;
                if (calls === 1) return { ok: false, json: async () => ({}) };
                return { ok: true, json: async () => ({ s: 'ok', c: [3], t: [3], o: [], h: [], l: [], v: [] }) };
            }));
            const result = await getCandles('SAN.MC', 1, 2);
            expect(result.source).toBe('Yahoo Finance');
            expect(calls).toBe(2);

            // Apagón total una hora después: sirve el último dato bueno (stale 6 h).
            vi.setSystemTime(new Date('2026-11-19T11:00:00Z'));
            vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })));
            const stale = await getCandles('SAN.MC', 1, 2);
            expect(stale.c).toEqual([3]);
        } finally {
            vi.useRealTimers();
        }
    });

    it('getPopularStocks: perfil sin nombre usa el ticker y bolsa desconocida -> US', async () => {
        const { getPopularStocks } = await loadModule('key');
        fetchJSON.mockResolvedValue({ ticker: 'AAPL' });
        const result = await getPopularStocks();
        expect(result.status).toBe('ok');
        if (result.status !== 'ok') return;
        expect(result.stocks[0]?.name).toBe('AAPL');
        expect(result.stocks[0]?.exchange).toBe('US');
    });

    it('getPopularStocks: mapea bolsas largas del proveedor a mercado legible', async () => {
        const { getPopularStocks } = await loadModule('key');
        fetchJSON.mockImplementation(async (url: string) => {
            const sym = new URL(url).searchParams.get('symbol');
            const exchanges: Record<string, string> = {
                AAPL: 'NYSE AMERICAN', MSFT: 'NYSE ARCA', GOOGL: 'NEW YORK STOCK EXCHANGE', AMZN: 'BATS',
            };
            return { ticker: sym, name: `${sym} Co`, exchange: exchanges[sym ?? ''] ?? 'Bursa Malaysia' };
        });
        const result = await getPopularStocks();
        if (result.status !== 'ok') throw new Error('expected ok');
        const bySymbol = Object.fromEntries(result.stocks.map((s) => [s.symbol, s.exchange]));
        expect(bySymbol.AAPL).toBe('NYSE American');
        expect(bySymbol.MSFT).toBe('NYSE Arca');
        expect(bySymbol.GOOGL).toBe('NYSE');
        expect(bySymbol.AMZN).toBe('Cboe');
    });

    it('getStockQuote: Finnhub sin dato válido y backend roto o sin dato -> null, nunca inventa', async () => {
        const { getStockQuote } = await loadModule('key');
        fetchJSON.mockResolvedValue(null);
        expect(await getStockQuote('AAPL')).toBeNull();

        process.env.FMP_BACKEND_URL = 'https://backend.example';
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ garbage: true }) })));
        expect(await getStockQuote('AAPL')).toBeNull();

        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network'); }));
        expect(await getStockQuote('AAPL')).toBeNull();
    });
});
