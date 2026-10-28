import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, cacheStore } = vi.hoisted(() => ({
    researchRequest: vi.fn<(...args: any[]) => any>(async () => ({})),
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(async () => ({ id: 'user-1' })),
    cacheStore: new Map<string, unknown>(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/cache/memoryTTL', () => ({
    cachedFetch: (key: string, fetcher: () => Promise<unknown>, _ttl: number) => {
        if (cacheStore.has(key)) return Promise.resolve(cacheStore.get(key));
        return fetcher().then((v) => { cacheStore.set(key, v); return v; });
    },
}));

import { getMarketRegimeResult } from '@/lib/actions/market-regime.actions';
import { getMarketMoversResult, getMarketMovers, getMarketIndicesResult, getMarketIndices } from '@/lib/actions/market.actions';
import { generateWorkProduct } from '@/lib/actions/work-products.actions';
import { getCalendarFeed, createCalendarFeed, revokeCalendarFeed } from '@/lib/actions/calendar-feed.actions';
import { getAstOrbitOverview, getAstsAnalysis } from '@/lib/actions/asts-orbits.actions';
import { askKnowledge } from '@/lib/actions/knowledge-chat.actions';
import { getMacroEvents, getEightKDigest } from '@/lib/actions/macro-calendar.actions';
import { getMarketThemes } from '@/lib/actions/market-themes.actions';

beforeEach(() => {
    vi.resetAllMocks();
    researchRequest.mockResolvedValue({});
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
    cacheStore.clear();
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('market-regime: datos o error, nunca un «sin datos» inventado', () => {
    it('payload válido -> data; backend caído -> error; payload vacío -> error', async () => {
        researchRequest.mockResolvedValue({ status: 'disponible', metrics: {} });
        expect(await getMarketRegimeResult()).toMatchObject({ data: { status: 'disponible' }, error: null });
        cacheStore.clear();
        researchRequest.mockRejectedValue(new Error('5xx'));
        const failed = await getMarketRegimeResult();
        expect(failed.data).toBeNull();
        expect(failed.error).toBeInstanceOf(Error);
        researchRequest.mockResolvedValue(null);
        expect((await getMarketRegimeResult()).data).toBeNull();
    });
});

describe('market movers e índices', () => {
    it('movers: payload sin las tres listas -> error discriminado, no universo vacío', async () => {
        researchRequest.mockResolvedValue({ gainers: [], losers: [], most_active: [] });
        expect(await getMarketMoversResult()).toMatchObject({ error: null });
        cacheStore.clear();
        researchRequest.mockResolvedValue({ gainers: [] });
        expect((await getMarketMoversResult()).data).toBeNull();
    });

    it('getMarketMovers legacy: con error devuelve el stub declarado', async () => {
        researchRequest.mockRejectedValue(new Error('caído'));
        expect(await getMarketMovers()).toEqual({ as_of: null, universe: 0, gainers: [], losers: [], most_active: [] });
    });

    it('índices: la unidad se normaliza por símbolo, nunca USD por defecto (F152)', async () => {
        researchRequest.mockResolvedValue({ indices: [
            { symbol: '^GSPC', name: 'S&P', price: 6000, change: 1, changePercent: 0.1 },
            { symbol: 'BTC-USD', name: 'Bitcoin', price: 100000, change: 1, changePercent: 0.1, unit: 'usd' },
            { symbol: 'DESCONOCIDO', name: '?', price: 1, change: 0, changePercent: 0 },
        ] });
        const { data, error } = await getMarketIndicesResult();
        expect(error).toBeNull();
        expect(data[0].unit).toBe('index');   // prefijo ^ -> nivel de índice
        expect(data[1].unit).toBe('usd');
        expect(data[2].unit).toBeUndefined(); // desconocido: sin sufijo monetario
    });

    it('índices caídos -> data [] CON error (no pliega el fallo)', async () => {
        researchRequest.mockRejectedValue(new Error('caído'));
        const result = await getMarketIndicesResult();
        expect(result.data).toEqual([]);
        expect(result.error).toBeInstanceOf(Error);
        expect(await getMarketIndices()).toEqual([]);
    });

    it('la caché evita refetch dentro de la ventana', async () => {
        researchRequest.mockResolvedValue({ gainers: [], losers: [], most_active: [] });
        await getMarketMoversResult(10);
        await getMarketMoversResult(10);
        expect(researchRequest).toHaveBeenCalledTimes(1);
    });
});

describe('work-products', () => {
    it('tipo obligatorio; ticker normalizado o null; años inválidos -> 10', async () => {
        await expect(generateWorkProduct({ product_type: '' as never, years: 5 })).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        researchRequest.mockResolvedValue({ markdown: '# memo' });
        await generateWorkProduct({ product_type: 'one_page_memo', ticker: ' aapl ', years: Number.NaN });
        expect(JSON.parse(researchRequest.mock.calls[0][1].body)).toEqual({ product_type: 'one_page_memo', ticker: 'AAPL', years: 10 });
        await generateWorkProduct({ product_type: 'risk_report', years: 5 });
        expect(JSON.parse(researchRequest.mock.calls[1][1].body)).toEqual({ product_type: 'risk_report', ticker: null, years: 5 });
    });
});

describe('calendar-feed: el token solo se muestra al crear', () => {
    it('estado/crear/revocar con sus métodos', async () => {
        researchRequest.mockResolvedValue({ active: false });
        await getCalendarFeed();
        expect(researchRequest).toHaveBeenCalledWith('/api/calendar/feed');
        await createCalendarFeed('followed');
        expect(researchRequest).toHaveBeenCalledWith('/api/calendar/feed', { method: 'POST', body: JSON.stringify({ scope: 'followed' }) });
        await revokeCalendarFeed();
        expect(researchRequest).toHaveBeenCalledWith('/api/calendar/feed', { method: 'DELETE' });
    });
});

describe('asts-orbits', () => {
    it('overview sin caché; análisis caído -> null (panel opcional)', async () => {
        researchRequest.mockResolvedValue({ status: 'disponible' });
        await getAstOrbitOverview();
        expect(researchRequest).toHaveBeenCalledWith('/api/market/asts/orbits', { cache: 'no-store', fast: true });
        researchRequest.mockRejectedValue(new Error('timeout'));
        expect(await getAstsAnalysis()).toBeNull();
    });
});

describe('knowledge-chat', () => {
    it('pregunta fuera de 3..1200 -> error antes de llamar', async () => {
        await expect(askKnowledge('ab', 'library')).rejects.toThrow('3 a 1200');
        await expect(askKnowledge('x'.repeat(1201), 'letters')).rejects.toThrow('3 a 1200');
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('analisis tiene presupuesto de 90 s; respuesta 60 s; body con trim y nulos explícitos', async () => {
        researchRequest.mockResolvedValue({ status: 'ok' });
        await askKnowledge('  ¿Qué dice Buffett de la deuda?  ', 'letters', undefined, 'analisis');
        expect(researchRequest).toHaveBeenCalledWith('/api/knowledge/chat', expect.objectContaining({ timeoutMs: 90000 }));
        expect(JSON.parse(researchRequest.mock.calls[0][1].body)).toEqual({
            question: '¿Qué dice Buffett de la deuda?', scope: 'letters', author: null, mode: 'analisis', page: null,
        });
        await askKnowledge('pregunta suficientemente larga', 'library', 'Buffett');
        expect(researchRequest).toHaveBeenCalledWith('/api/knowledge/chat', expect.objectContaining({ timeoutMs: 60000 }));
    });
});

describe('macro-calendar y market-themes', () => {
    it('paginación fija en la query', async () => {
        researchRequest.mockResolvedValue({ events: [] });
        await getMacroEvents(3);
        expect(String(researchRequest.mock.calls[0][0])).toBe('/api/macro-calendar/events?page=3&page_size=10');
        await getEightKDigest(2);
        expect(String(researchRequest.mock.calls[1][0])).toBe('/api/macro-calendar/8k?page=2&page_size=5');
    });

    it('themes: payload inválido -> error (no ranking vacío que parezca un dato)', async () => {
        researchRequest.mockResolvedValue({ themes: [] });
        expect(await getMarketThemes()).toEqual({ themes: [] });
        researchRequest.mockResolvedValue(null);
        await expect(getMarketThemes()).rejects.toThrow('no válida');
    });
});

describe('knowledge document context', () => {
    it('sends only the explicitly selected document ID', async () => {
        await askKnowledge('Pregunta de la carta', 'letters', undefined, 'respuesta', null, 42);
        const opts = researchRequest.mock.calls.at(-1)![1];
        expect(JSON.parse(opts.body).document_id).toBe(42);
    });
});
