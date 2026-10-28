import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, fetchDatedChanges } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
    fetchDatedChanges: vi.fn(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/market/dated-change', () => ({ fetchDatedChanges }));

import { formatNumber } from '@/lib/format';
import {
    exportScreenerResults,
    getScreenerStocksReal,
    getScreenerStocksRealWithStatus,
    getFairValueReading,
    runScreenerEngine,
    runSavedScreenerEngine,
    getSavedScreenerEngines,
    type ScreenerFilters,
    type ScreenerResult,
} from '@/lib/actions/screener.actions';

const WIDE: ScreenerFilters = {
    marketCapMin: 0, marketCapMax: Number.POSITIVE_INFINITY,
    priceMin: 0, priceMax: Number.POSITIVE_INFINITY,
    peMin: Number.NEGATIVE_INFINITY, peMax: Number.POSITIVE_INFINITY,
    pbMin: Number.NEGATIVE_INFINITY, pbMax: Number.POSITIVE_INFINITY,
    roeMin: Number.NEGATIVE_INFINITY, roeMax: Number.POSITIVE_INFINITY,
    volumeMin: 0, betaMin: Number.NEGATIVE_INFINITY, betaMax: Number.POSITIVE_INFINITY,
    sector: 'all', exchange: 'all', assetType: 'all', sortBy: 'marketCap', sortOrder: 'desc',
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
});

describe('screenStocks (legacy Finnhub, cliente)', () => {
    const loadModule = async (apiKey?: string) => {
        vi.resetModules();
        if (apiKey === undefined) delete process.env.FINNHUB_API_KEY;
        else process.env.FINNHUB_API_KEY = apiKey;
        return import('@/lib/actions/screener.actions');
    };

    it('sin FINNHUB_API_KEY devuelve [] y no hace ninguna petición', async () => {
        const { screenStocks } = await loadModule(undefined);
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);
        expect(await screenStocks(WIDE)).toEqual([]);
        expect(fetchMock).not.toHaveBeenCalled();
        vi.unstubAllGlobals();
    });

    const seedFetch = () => {
        const quote: Record<string, object> = {
            AAPL: { c: 150, d: 1.5, dp: 1, v: 5_000_000 },
            MSFT: { c: 300, d: -3, dp: -1, v: 2_000_000 },
            SPY: { c: 500, d: null, dp: null, v: 50_000_000 },
        };
        const profile: Record<string, object> = {
            AAPL: { name: 'Apple', marketCapitalization: 2_500_000, finnhubIndustry: 'Technology', exchange: 'NASDAQ' },
            MSFT: { name: 'Microsoft', marketCapitalization: 3_000_000, finnhubIndustry: 'Technology', exchange: 'NASDAQ' },
            SPY: { name: 'SPDR S&P 500', marketCapitalization: 500_000, finnhubIndustry: 'ETF', exchange: 'NYSE' },
        };
        const metric: Record<string, object> = {
            AAPL: { metric: { peBasicExclExtraTTM: 25, pbAnnual: 30, roeTTM: 150, beta: 1.2 } },
            MSFT: { metric: { peBasicExclExtraTTM: 35, pbAnnual: 12, roeTTM: 40, beta: 0.9 } },
            SPY: { metric: {} },
        };
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            const symbol = new URL(url).searchParams.get('symbol') ?? '';
            if (!(symbol in quote)) return { ok: true, json: async () => ({ c: 0 }) } as Response;
            if (url.includes('/quote')) return { ok: true, json: async () => quote[symbol] } as Response;
            if (url.includes('/profile2')) return { ok: true, json: async () => profile[symbol] } as Response;
            return { ok: true, json: async () => metric[symbol] } as Response;
        }));
    };

    it('mapea market cap a dólares (x1e6), detecta ETF y ordena por market cap desc', async () => {
        const { screenStocks } = await loadModule('test-key');
        seedFetch();
        const rows = await screenStocks(WIDE);
        expect(rows.map((r) => r.symbol)).toEqual(['MSFT', 'AAPL', 'SPY']);
        expect(rows.find((r) => r.symbol === 'AAPL')).toMatchObject({
            marketCap: 2_500_000_000_000, type: 'Stock', sector: 'Technology', pe: 25, beta: 1.2,
        });
        expect(rows.find((r) => r.symbol === 'SPY')).toMatchObject({ type: 'ETF', change: null, changePercent: null });
        vi.unstubAllGlobals();
    });

    it('orden asc invierte la lista', async () => {
        const { screenStocks } = await loadModule('test-key');
        seedFetch();
        const rows = await screenStocks({ ...WIDE, sortOrder: 'asc' });
        expect(rows.map((r) => r.symbol)).toEqual(['SPY', 'AAPL', 'MSFT']);
        vi.unstubAllGlobals();
    });

    it('filtros de precio y tipo descartan lo que no encaja', async () => {
        const { screenStocks } = await loadModule('test-key');
        seedFetch();
        const caras = await screenStocks({ ...WIDE, priceMin: 200 });
        expect(caras.map((r) => r.symbol).sort()).toEqual(['MSFT', 'SPY']);
        const etfs = await screenStocks({ ...WIDE, assetType: 'ETF' });
        expect(etfs.map((r) => r.symbol)).toEqual(['SPY']);
        vi.unstubAllGlobals();
    });

    it('quote sin precio (c=0) y perfil caído no producen fila', async () => {
        const { screenStocks } = await loadModule('test-key');
        seedFetch();
        const rows = await screenStocks({ ...WIDE, priceMin: 1 });
        expect(rows.some((r) => r.price === 0)).toBe(false);
        vi.unstubAllGlobals();
    });
});

describe('exportScreenerResults', () => {
    const row: ScreenerResult = {
        symbol: 'AAPL', name: 'Apple', price: 150, change: 1.5, changePercent: 1,
        marketCap: 2_500_000_000_000, pe: 25, pb: 30, roe: 150, volume: 5_000_000,
        beta: 1.2, sector: 'Technology', exchange: 'NASDAQ', type: 'Stock',
    };

    it('genera CSV con cabecera y valores formateados igual que la UI', async () => {
        const csv = await exportScreenerResults([row]);
        const lines = csv.split('\n');
        expect(lines[0]).toBe('Symbol,Name,Price,Change,Change %,Market Cap,P/E,P/B,ROE,Volume,Beta,Sector,Exchange,Type');
        expect(lines).toHaveLength(2);
        const fmt = (v: number, d = 2) => formatNumber(v, { minimumFractionDigits: d, maximumFractionDigits: d });
        expect(lines[1]).toBe([
            'AAPL', 'Apple', fmt(150), fmt(1.5), fmt(1),
            formatNumber(2_500_000_000_000, { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
            fmt(25), fmt(30), fmt(150),
            formatNumber(5_000_000, { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
            fmt(1.2), 'Technology', 'NASDAQ', 'Stock',
        ].join(','));
    });

    it('exige sesión', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('No autenticado'));
        await expect(exportScreenerResults([row])).rejects.toThrow('No autenticado');
    });
});

describe('getScreenerStocksRealWithStatus', () => {
    const baseRow = {
        symbol: 'AAPL', name: 'Apple', price: 999, change: 0, changePercent: 0,
        marketCap: 1, volume: 1, prevClose: 998, sector: 'Technology', exchange: 'NASDAQ',
        type: 'Stock', pe: null, pb: null, roe: null, beta: null,
    };

    it('construye la query (limit 25 por defecto) y sobrescribe precio con cierres datados', async () => {
        researchRequest.mockResolvedValue({ screener: [baseRow], universe_size: 1200 });
        fetchDatedChanges.mockResolvedValue({
            AAPL: { price: 151.2, currency: 'USD', change: 1.2, changePercent: 0.8, previousClose: 150, date: '2026-10-27' },
        });
        const result = await getScreenerStocksRealWithStatus({ marketCapMoreThan: 1e9, sector: 'Technology' });
        expect(researchRequest).toHaveBeenCalledWith('/api/screeners/real?marketCapMoreThan=1000000000&sector=Technology&limit=25', { cache: 'no-store' });
        expect(result.rows[0]).toMatchObject({ price: 151.2, currency: 'USD', changePercent: 0.8, priceDate: '2026-10-27' });
        expect(result.refreshing).toBe(false);
        expect(result.unavailable).toBe(false);
        expect(result.universeSize).toBe(1200);
    });

    it('sin cierre datado conserva la fila original', async () => {
        researchRequest.mockResolvedValue({ screener: [baseRow] });
        fetchDatedChanges.mockResolvedValue({});
        const result = await getScreenerStocksReal();
        expect(result[0].price).toBe(999);
        expect(result[0].priceDate).toBeUndefined();
    });

    it('vacío + unavailable + sin refresh -> unavailable (proveedor sin datos, no filtro sin resultados)', async () => {
        researchRequest.mockResolvedValue({ screener: [], unavailable: true });
        fetchDatedChanges.mockResolvedValue({});
        const result = await getScreenerStocksRealWithStatus();
        expect(result).toEqual({ rows: [], refreshing: false, unavailable: true, universeSize: null });
    });

    it('vacío con refresh en vuelo -> refreshing, no unavailable', async () => {
        researchRequest.mockResolvedValue({ screener: [], unavailable: true, refreshing: true });
        fetchDatedChanges.mockResolvedValue({});
        const result = await getScreenerStocksRealWithStatus();
        expect(result.refreshing).toBe(true);
        expect(result.unavailable).toBe(false);
    });
});

describe('getFairValueReading: la misma cifra en todas las páginas', () => {
    it('valor válido con fuente conocida -> lectura con precedencia declarada', async () => {
        researchRequest.mockResolvedValue({ value: 185.5, source: 'tesis', label: 'Tesis publicada v3', publishable: true, as_of: '2026-10-20' });
        expect(await getFairValueReading('AAPL')).toEqual({
            value: 185.5, publishable: true, source: 'tesis', label: 'Tesis publicada v3', asOf: '2026-10-20',
        });
        expect(researchRequest).toHaveBeenCalledWith('/api/valuation/AAPL/fair-value', { cache: 'no-store' });
    });

    it('sin valor, valor <= 0 o fuente desconocida -> null (nunca un número inventado)', async () => {
        researchRequest.mockResolvedValue({ value: null, source: 'tesis' });
        expect(await getFairValueReading('AAPL')).toBeNull();
        researchRequest.mockResolvedValue({ value: -3, source: 'motor' });
        expect(await getFairValueReading('AAPL')).toBeNull();
        researchRequest.mockResolvedValue({ value: 100, source: 'gpt-lo-dijo' });
        expect(await getFairValueReading('AAPL')).toBeNull();
    });

    it('motor orientativo no publicable se declara publishable=false con etiqueta por defecto', async () => {
        researchRequest.mockResolvedValue({ value: 42, source: 'motor_orientativo' });
        expect(await getFairValueReading('AAPL')).toEqual({
            value: 42, publishable: false, source: 'motor_orientativo', label: 'Valor justo', asOf: null,
        });
    });

    it('fallo de red -> null', async () => {
        researchRequest.mockRejectedValue(new Error('boom'));
        expect(await getFairValueReading('AAPL')).toBeNull();
    });
});

describe('motor de screener', () => {
    const criteria = [{ left: 'pe', operator: '<' as const, right: '15' }];

    it('sin criterios -> error antes de llamar al backend', async () => {
        await expect(runScreenerEngine([])).rejects.toThrow('Define al menos un criterio');
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('POST con fórmula y dirección por defecto desc', async () => {
        researchRequest.mockResolvedValue({ results: [] });
        await runScreenerEngine(criteria);
        expect(researchRequest).toHaveBeenCalledWith('/api/screeners/run', {
            method: 'POST',
            body: JSON.stringify({ criteria, ranking_formula: null, ranking_direction: 'desc' }),
        });
    });

    it('filtro guardado: id no entero o <= 0 -> error sin llamada', async () => {
        await expect(runSavedScreenerEngine(0)).rejects.toThrow('Filtro no válido');
        await expect(runSavedScreenerEngine(1.5)).rejects.toThrow('Filtro no válido');
        expect(researchRequest).not.toHaveBeenCalled();
        researchRequest.mockResolvedValue({ results: [] });
        await runSavedScreenerEngine(3);
        expect(researchRequest).toHaveBeenCalledWith('/api/screeners/screens/3/run', { method: 'POST' });
    });

    it('lista de filtros guardados sin caché', async () => {
        researchRequest.mockResolvedValue([{ id: 1, name: 'Marco Nico' }]);
        expect(await getSavedScreenerEngines()).toEqual([{ id: 1, name: 'Marco Nico' }]);
        expect(researchRequest).toHaveBeenCalledWith('/api/screeners/screens', { cache: 'no-store' });
    });
});
