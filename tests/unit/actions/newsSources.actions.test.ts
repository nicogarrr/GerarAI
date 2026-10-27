import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser } = vi.hoisted(() => ({ requireAuthenticatedUser: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));

import { getNewsWithFallback, getCompanyNewsWithFallback } from '@/lib/actions/newsSources.actions';

const KEYS = ['FINNHUB_API_KEY', 'ALPHA_VANTAGE_API_KEY', 'NEWSAPI_KEY', 'MARKETAUX_API_KEY'] as const;

const finnhubArticle = (over: object = {}) => ({
    id: 1, headline: 'Apple beats earnings expectations', summary: 'Apple stock rises after strong revenue.',
    url: 'https://news.example/aapl-1', datetime: 1_700_000_000, source: 'Reuters', image: '', ...over,
});

/** fetch router: cada proveedor responde según la URL pedida. */
const stubFetch = (routes: Array<[string, object]>) => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        const u = String(url);
        calls.push(u);
        for (const [match, payload] of routes) {
            if (u.includes(match)) return { ok: true, json: async () => payload } as Response;
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
    }));
    return calls;
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    for (const k of KEYS) delete process.env[k];
});

afterEach(() => {
    vi.unstubAllGlobals();
    for (const k of KEYS) delete process.env[k];
});

describe('getNewsWithFallback', () => {
    it('exige sesión antes de llamar a ningún proveedor', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('No autenticado'));
        const calls = stubFetch([]);
        await expect(getNewsWithFallback(['AAPL'])).rejects.toThrow('No autenticado');
        expect(calls).toHaveLength(0);
    });

    it('sin ninguna clave configurada -> []', async () => {
        const calls = stubFetch([]);
        expect(await getNewsWithFallback(['AAPL'])).toEqual([]);
        expect(calls).toHaveLength(0);
    });

    it('Finnhub con símbolos: normaliza, pide por empresa con rango de 5 días y ordena por fecha desc', async () => {
        process.env.FINNHUB_API_KEY = 'fh-key';
        const calls = stubFetch([
            ['company-news?symbol=AAPL', [finnhubArticle({ datetime: 100 }), finnhubArticle({ url: 'https://news.example/aapl-2', datetime: 300 })]],
            ['company-news?symbol=MSFT', [finnhubArticle({ url: 'https://news.example/msft-1', datetime: 200, headline: 'Microsoft stock gains' })]],
        ]);
        const news = await getNewsWithFallback([' aapl ', 'msft'], 6);
        const companyCalls = calls.filter((u) => u.includes('company-news'));
        expect(companyCalls).toHaveLength(2);
        expect(companyCalls[0]).toMatch(/from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}&token=fh-key/);
        expect(news.map((a) => a.datetime)).toEqual([300, 200, 100]);
        expect(news.every((a) => a.category === 'company')).toBe(true);
    });

    it('artículos sin campos mínimos (headline/summary/url/datetime) no entran', async () => {
        process.env.FINNHUB_API_KEY = 'fh-key';
        stubFetch([
            ['company-news', [
                finnhubArticle({ summary: '' }),
                finnhubArticle({ url: 'https://news.example/ok', headline: 'Good stock news' }),
            ]],
        ]);
        const news = await getNewsWithFallback(['AAPL']);
        expect(news).toHaveLength(1);
        expect(news[0].url).toBe('https://news.example/ok');
    });

    it('sin noticias de empresa cae al general y deduplica por id+url+headline', async () => {
        process.env.FINNHUB_API_KEY = 'fh-key';
        const calls = stubFetch([
            ['company-news', []],
            ['news?category=general', [
                finnhubArticle({ id: 9, url: 'https://news.example/dup', datetime: 500 }),
                finnhubArticle({ id: 9, url: 'https://news.example/dup', datetime: 500 }),
            ]],
        ]);
        const news = await getNewsWithFallback(['AAPL']);
        expect(calls.some((u) => u.includes('news?category=general'))).toBe(true);
        expect(news).toHaveLength(1);
    });

    it('Alpha Vantage: datetime desde time_published y related = primer símbolo', async () => {
        process.env.ALPHA_VANTAGE_API_KEY = 'av-key';
        stubFetch([
            ['alphavantage.co', {
                feed: [
                    { title: 'Stocks rally on inflation data', summary: 'Markets up', url: 'https://news.example/av-1', time_published: '2026-10-27T10:30:00', source: 'AV', banner_image: '' },
                    { title: '', summary: 'sin titular', url: 'https://news.example/av-2', time_published: '2026-10-27T10:30:00' },
                ],
            }],
        ]);
        const news = await getNewsWithFallback(['AAPL']);
        expect(news).toHaveLength(1);
        expect(news[0]).toMatchObject({ url: 'https://news.example/av-1', related: 'AAPL', source: 'AV' });
        expect(news[0].datetime).toBe(new Date('2026-10-27T10:30:00').getTime() / 1000);
        expect(news[0].id).toMatch(/^av-/);
    });

    it('NewsAPI: query con los símbolos (máx 3) y summary cae a content si falta description', async () => {
        process.env.NEWSAPI_KEY = 'napi-key';
        const calls = stubFetch([
            ['newsapi.org', {
                articles: [{
                    title: 'Market update: stocks climb', description: null, content: 'Stocks climbed today.',
                    url: 'https://news.example/napi-1', publishedAt: '2026-10-27T12:00:00Z', source: { name: 'NewsAPI' },
                }],
            }],
        ]);
        const news = await getNewsWithFallback(['AAPL', 'MSFT', 'GOOGL', 'AMZN']);
        const query = calls[0].match(/[?&]q=([^&]*)/)?.[1];
        expect(query).toBe('AAPL%20OR%20MSFT%20OR%20GOOGL');
        expect(query).not.toContain('AMZN');
        expect(news[0].summary).toBe('Stocks climbed today.');
        expect(news[0].id).toMatch(/^newsapi-/);
    });

    it('Marketaux: id desde uuid', async () => {
        process.env.MARKETAUX_API_KEY = 'mx-key';
        stubFetch([
            ['marketaux.com', {
                data: [{ uuid: 'uuid-1', title: 'Earnings season starts', description: 'Stocks earnings', url: 'https://news.example/mx-1', published_at: '2026-10-27T12:00:00Z', source: 'Marketaux' }],
            }],
        ]);
        const news = await getNewsWithFallback(['AAPL']);
        expect(news[0].id).toBe('marketaux-uuid-1');
    });

    it('agrega fuentes: deduplica por URL normalizada, filtra lo no financiero y limita', async () => {
        process.env.ALPHA_VANTAGE_API_KEY = 'av-key';
        process.env.MARKETAUX_API_KEY = 'mx-key';
        stubFetch([
            ['alphavantage.co', {
                feed: [
                    { title: 'Parenting tips for toddlers', summary: 'How to raise kids', url: 'https://NEWS.example/SAME', time_published: '2026-10-27T10:00:00' },
                    { title: 'Stocks surge on earnings', summary: 'Market rally', url: 'https://news.example/other', time_published: '2026-10-26T10:00:00' },
                ],
            }],
            ['marketaux.com', {
                data: [{ uuid: 'm1', title: 'Markets up', description: 'stocks', url: 'https://news.example/same', published_at: '2026-10-27T11:00:00Z' }],
            }],
        ]);
        const news = await getNewsWithFallback();
        const urls = news.map((a) => a.url);
        // la URL duplicada (distinta capitalización) entra una sola vez
        expect(urls.filter((u) => u.toLowerCase() === 'https://news.example/same')).toHaveLength(1);
        // el artículo de crianza no es noticia financiera
        expect(news.some((a) => a.headline.includes('Parenting'))).toBe(false);
        // ordenados por fecha desc
        expect(news.map((a) => a.datetime)).toEqual([...news.map((a) => a.datetime)].sort((x, y) => y - x));
    });

    it('un proveedor caído no tumba a los demás', async () => {
        process.env.FINNHUB_API_KEY = 'fh-key';
        process.env.MARKETAUX_API_KEY = 'mx-key';
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            if (String(url).includes('finnhub')) throw new Error('finnhub down');
            return {
                ok: true,
                json: async () => ({ data: [{ uuid: 'm1', title: 'Stocks rise', description: 'market', url: 'https://news.example/mx-1', published_at: '2026-10-27T11:00:00Z' }] }),
            } as Response;
        }));
        const news = await getNewsWithFallback(['AAPL']);
        expect(news).toHaveLength(1);
        expect(news[0].id).toBe('marketaux-m1');
    });
});

describe('getCompanyNewsWithFallback', () => {
    it('envuelve con el símbolo y maxArticles 20 por defecto', async () => {
        process.env.FINNHUB_API_KEY = 'fh-key';
        const calls = stubFetch([['company-news', [finnhubArticle()]]]);
        const news = await getCompanyNewsWithFallback('AAPL');
        expect(calls.some((u) => u.includes('symbol=AAPL'))).toBe(true);
        expect(news[0].related).toBe('AAPL');
    });
});
