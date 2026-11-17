import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

// /portfolio no debe esperar a las lecturas tolerantes (movimientos, factores,
// tearsheet, previsión y dividendos) para devolver el documento: solo el
// resumen es esencial; el resto llega como promesas que cada panel desenvuelve
// en su <Suspense> (medido en prod 17-nov-2026: TTFB 0,3 s pero primer
// contenido a los 9,6 s cuando la página esperaba a todas a la vez).
const m = vi.hoisted(() => ({
    summary: vi.fn(), transactions: vi.fn(), scores: vi.fn(),
    tearsheet: vi.fn(), forecast: vi.fn(), dividends: vi.fn(),
    requireUser: vi.fn(),
}));
vi.mock('@/lib/actions/portfolio.actions', () => ({
    getPortfolioSummary: m.summary,
    getPortfolioTransactionPage: m.transactions,
    getPortfolioScores: m.scores,
    getPortfolioTearsheet: m.tearsheet,
    getPortfolioForecast: m.forecast,
    getPortfolioDividendProjection: m.dividends,
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: m.requireUser }));
vi.mock('@/lib/i18n/server', () => ({
    getT: async () => (key: string, params?: Record<string, unknown>) => (params ? `${key}:${JSON.stringify(params)}` : key),
    getLocale: async () => 'es',
}));
vi.mock('@/components/portfolio/PortfolioTabs', () => ({ default: function PortfolioTabs() { return null; } }));
const signInRedirect = vi.hoisted(() => vi.fn(() => 'REDIRECT_TO_SIGNIN'));
vi.mock('@/lib/auth/sign-in-redirect', () => ({ redirectToSignIn: signInRedirect }));
vi.mock('@/components/research/ValuationSummaryGrid', () => ({ default: () => null }));
vi.mock('@/components/system/BackendOffline', () => ({ default: function BackendOffline() { return null; } }));

type El = { type?: { name?: string } | string; props?: Record<string, unknown> };
function find(node: unknown, name: string, out: El[] = []): El[] {
    if (Array.isArray(node)) node.forEach((n) => find(n, name, out));
    else if (node && typeof node === 'object') {
        const el = node as El;
        if (typeof el.type === 'function' && el.type.name === name) out.push(el);
        if (el.props) Object.values(el.props).forEach((v) => find(v, name, out));
    }
    return out;
}

const summaryValue = {
    totalValue: 10000, totalCost: 8000, totalGain: 2000, totalGainPercent: 25, baseCurrency: 'EUR', cash: 0,
    holdings: [{ symbol: 'A', currentPrice: 100, nativeCurrency: 'EUR' }], quality: undefined,
};

// Import/transform time is not page data latency (cold VM imports can exceed
// 1s): load the module before the streaming assertion's clock starts.
let PortfolioPage: typeof import('@/app/(root)/portfolio/page')['default'];
let generateMetadata: typeof import('@/app/(root)/portfolio/page')['generateMetadata'];
beforeAll(async () => {
    ({ default: PortfolioPage, generateMetadata } = await import('@/app/(root)/portfolio/page'));
});

beforeEach(() => {
    m.requireUser.mockResolvedValue({ id: 'u1' });
});

function mockTolerant(pending: boolean) {
    const value = { items: [], total: 0, offset: 0, filters: {} };
    m.transactions.mockReturnValue(pending ? new Promise(() => {}) : Promise.resolve(value));
    m.scores.mockReturnValue(pending ? new Promise(() => {}) : Promise.resolve({ quality: 1, growth: 1, value: 1, dividend: 1, cagr3y: 1 }));
    m.tearsheet.mockReturnValue(pending ? new Promise(() => {}) : Promise.resolve(null));
    m.forecast.mockReturnValue(pending ? new Promise(() => {}) : Promise.resolve(null));
    m.dividends.mockReturnValue(pending ? new Promise(() => {}) : Promise.resolve(null));
}

describe('portfolio: la latencia de los módulos no es la latencia del documento', () => {
    it('devuelve la página con las lecturas tolerantes aún pendientes', async () => {
        m.summary.mockResolvedValue(summaryValue);
        mockTolerant(true);
        const started = performance.now();
        const result = await Promise.race([
            PortfolioPage({ searchParams: Promise.resolve({}) }),
            new Promise((resolve) => setTimeout(() => resolve('blocked'), 2500)),
        ]);
        console.log('SIMULATED tolerant=pending document_ms=' + Math.round(performance.now() - started));
        expect(result).not.toBe('blocked');
        const tabs = find(result, 'PortfolioTabs');
        expect(tabs.length).toBe(1);
        for (const prop of ['transactions', 'scores', 'tearsheet', 'forecast', 'dividends', 'partialMessage']) {
            expect(tabs[0].props?.[prop]).toBeInstanceOf(Promise);
        }
        expect(tabs[0].props?.summary).toEqual(summaryValue);
    });

    it('un fallo de resumen degrada al aviso con Reintentar, nunca a un 500', async () => {
        m.summary.mockRejectedValue(new Error('backend 500'));
        mockTolerant(true);
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        expect(find(result, 'BackendOffline').length).toBe(1);
    });

    it('el aviso de lectura parcial se resuelve sin bloquear y solo con errores', async () => {
        m.summary.mockResolvedValue(summaryValue);
        mockTolerant(false);
        m.scores.mockRejectedValue(new Error('timeout'));
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        const tabs = find(result, 'PortfolioTabs');
        const partial = await (tabs[0].props?.partialMessage as Promise<string | null>);
        expect(partial).toContain('portfolio.page.partialPrefix');
    });

    it('un fallo de sesión al leer el resumen vuelve al login', async () => {
        const { AuthenticationError } = await import('@/lib/types/errors');
        m.summary.mockRejectedValue(new AuthenticationError('sesión caducada'));
        mockTolerant(true);
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        expect(result).toBe('REDIRECT_TO_SIGNIN');
        expect(signInRedirect).toHaveBeenCalled();
    });

    it('sin errores tolerantes el aviso se resuelve a null', async () => {
        m.summary.mockResolvedValue(summaryValue);
        mockTolerant(false);
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        const tabs = find(result, 'PortfolioTabs');
        await expect(tabs[0].props?.partialMessage as Promise<string | null>).resolves.toBeNull();
    });
});

describe('portfolio: ramas de error y metadatos', () => {
    it('generateMetadata traduce título y descripción', async () => {
        m.summary.mockResolvedValue(summaryValue);
        await expect(generateMetadata()).resolves.toEqual({
            title: 'portfolio.page.metaTitle', description: 'portfolio.page.metaDescription',
        });
    });

    it('sin sesión válida redirige al login sin lanzar lecturas', async () => {
        m.requireUser.mockRejectedValue(new Error('no session'));
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        expect(result).toBe('REDIRECT_TO_SIGNIN');
        expect(m.summary).not.toHaveBeenCalled();
    });

    it('transactionOffset inválido o negativo cae a 0 y el válido se respeta', async () => {
        m.summary.mockResolvedValue(summaryValue);
        mockTolerant(false);
        await PortfolioPage({ searchParams: Promise.resolve({ transactionOffset: 'abc' }) });
        expect(m.transactions).toHaveBeenLastCalledWith('u1', 0, expect.anything());
        await PortfolioPage({ searchParams: Promise.resolve({ transactionOffset: '-3' }) });
        expect(m.transactions).toHaveBeenLastCalledWith('u1', 0, expect.anything());
        await PortfolioPage({ searchParams: Promise.resolve({ transactionOffset: '2' }) });
        expect(m.transactions).toHaveBeenLastCalledWith('u1', 2, expect.anything());
    });

    it('los fallos tolerantes llegan a cada panel como { value, error } sin romper la página', async () => {
        m.summary.mockResolvedValue(summaryValue);
        m.transactions.mockRejectedValue(new Error('backend timeout'));
        m.scores.mockResolvedValue({ quality: 1, growth: 1, value: 1, dividend: 1, cagr3y: 1 });
        m.tearsheet.mockRejectedValue(new Error('backend timeout'));
        m.forecast.mockRejectedValue(new Error('backend timeout'));
        m.dividends.mockRejectedValue(new Error('backend timeout'));
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        const tabs = find(result, 'PortfolioTabs');
        const txs = await tabs[0].props?.transactions as { value: { items: unknown[] }; error: string | null };
        expect(txs.value.items).toEqual([]);
        expect(txs.error).toBeTruthy();
        for (const prop of ['tearsheet', 'forecast', 'dividends']) {
            const r = await tabs[0].props?.[prop] as { value: unknown; error: string | null };
            expect(r.value).toBeNull();
            expect(r.error).toBeTruthy();
        }
        const partial = await tabs[0].props?.partialMessage as string | null;
        expect(partial).toContain('portfolio.page.partialPrefix');
    });

    it('un fallo tolerante que no es Error usa el texto genérico localizado', async () => {
        m.summary.mockResolvedValue(summaryValue);
        m.transactions.mockRejectedValue('caido' as never);
        m.scores.mockRejectedValue('caido' as never);
        m.tearsheet.mockRejectedValue('caido' as never);
        m.forecast.mockRejectedValue('caido' as never);
        m.dividends.mockRejectedValue('caido' as never);
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        const tabs = find(result, 'PortfolioTabs');
        const expected: Record<string, string> = {
            transactions: 'portfolio.page.loadTransactionsFailed',
            scores: 'portfolio.page.loadScoresFailed',
            tearsheet: 'portfolio.page.loadTearsheetFailed',
            forecast: 'portfolio.page.loadForecastFailed',
            dividends: 'portfolio.page.loadDividendsFailed',
        };
        for (const [prop, key] of Object.entries(expected)) {
            const r = await tabs[0].props?.[prop] as { error: string | null };
            expect(r.error).toBe(key);
        }
    });

    it('un fallo de resumen que no es Error también degrada al aviso', async () => {
        m.summary.mockRejectedValue('caido' as never);
        mockTolerant(false);
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        expect(find(result, 'BackendOffline').length).toBe(1);
    });

    it('backend caído de forma síncrona degrada al aviso con Reintentar', async () => {
        const { ExternalAPIError } = await import('@/lib/types/errors');
        m.summary.mockImplementation(() => { throw new ExternalAPIError('ECONNREFUSED', 'backend'); });
        mockTolerant(false);
        const result = await PortfolioPage({ searchParams: Promise.resolve({}) });
        expect(find(result, 'BackendOffline').length).toBe(1);
    });

    it('un error que no es de backend disponible se propaga', async () => {
        m.summary.mockImplementation(() => { throw new Error('bug inesperado'); });
        mockTolerant(false);
        await expect(PortfolioPage({ searchParams: Promise.resolve({}) })).rejects.toThrow('bug inesperado');
    });
});
