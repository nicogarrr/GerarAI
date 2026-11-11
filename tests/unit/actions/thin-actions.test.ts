import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, researchIdentityHeaders, requestCacheInvalidate, revalidatePath, getWatchlist } = vi.hoisted(() => ({
    researchRequest: vi.fn<(...args: any[]) => any>(async () => ({})),
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(async () => ({ id: 'user-1' })),
    researchIdentityHeaders: vi.fn<(...args: any[]) => any>(async () => ({ 'X-Tenant': 'user-1' })),
    requestCacheInvalidate: vi.fn<(...args: any[]) => any>(),
    revalidatePath: vi.fn<(...args: any[]) => any>(),
    getWatchlist: vi.fn<(...args: any[]) => any>(async () => []),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders }));
vi.mock('@/lib/cache/memoryTTL', () => ({ cachedFetch: (_k: string, f: () => Promise<unknown>) => f() }));
vi.mock('@/lib/cache/requestCache', () => ({ requestCache: { invalidate: requestCacheInvalidate } }));
vi.mock('next/cache', () => ({ revalidatePath }));
vi.mock('@/lib/actions/watchlist.actions', async (importActual) => ({
    ...(await importActual<typeof import('@/lib/actions/watchlist.actions')>()),
    getWatchlist,
}));

import { AppError, ExternalAPIError } from '@/lib/types/errors';
import { feedPaperProposalsNow, getPaperTrading } from '@/lib/actions/paper-trading.actions';
import { getHistoricalStress } from '@/lib/actions/historical-stress.actions';
import { getCorporateActions, applyCorporateAction, getCorporateActionsSyncStatus } from '@/lib/actions/corporate-actions.actions';
import { getCatalystCalendar, getFollowedEarnings } from '@/lib/actions/catalysts.actions';
import { getRiskDashboard } from '@/lib/actions/risk.actions';
import { getShareCapital } from '@/lib/actions/share-capital.actions';
import { previewPortfolioImage, searchImageInstrument, reviewPortfolioImage, confirmPortfolioImage } from '@/lib/actions/portfolio-image.actions';
import { getPortfolioCurrencySettings, savePortfolioBaseCurrency } from '@/lib/actions/portfolio-settings.actions';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';

const fetchMock = vi.fn<(...args: any[]) => any>();
vi.stubGlobal('fetch', fetchMock);

beforeEach(() => {
    vi.resetAllMocks();
    researchRequest.mockResolvedValue({});
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
    researchIdentityHeaders.mockResolvedValue({ 'X-Tenant': 'user-1' });
    getWatchlist.mockResolvedValue([]);
});

describe('paper-trading', () => {
    it('feed 202 -> success; AppError -> su mensaje; otro error -> genérico', async () => {
        expect(await feedPaperProposalsNow()).toEqual({ success: true });
        researchRequest.mockRejectedValue(new AppError('Cuota diaria agotada', 'RESEARCH_API_ERROR', 429));
        expect(await feedPaperProposalsNow()).toEqual({ success: false, message: 'Cuota diaria agotada' });
        researchRequest.mockRejectedValue(new Error('TypeError raro'));
        expect(await feedPaperProposalsNow()).toEqual({ success: false, message: 'No se pudo encolar la generación.' });
    });

    it('proveedor caído -> estado error declarado; 401/403 y errores inesperados propagan', async () => {
        researchRequest.mockRejectedValue(new AppError('boom', 'EXTERNAL_API_ERROR', 500));
        expect(await getPaperTrading()).toEqual({ trades: [], score: { groups: [] }, error: 'No se pudo cargar la cartera simulada.' });
        researchRequest.mockRejectedValue(new AppError('no auth', 'RESEARCH_API_ERROR', 401));
        await expect(getPaperTrading()).rejects.toThrow('no auth');
        researchRequest.mockRejectedValue(new Error('TypeError'));
        await expect(getPaperTrading()).rejects.toThrow('TypeError');
    });
});

describe('historical-stress', () => {
    it('no-ok -> AppError con status; red caída -> ExternalAPIError; ticker en query', async () => {
        // Usa el cliente común del motor (researchRequest): sus errores llegan tal cual.
        researchRequest.mockResolvedValue({ status: 'ok' });
        await getHistoricalStress('AAPL');
        expect(String(researchRequest.mock.calls[0][0])).toContain('/api/risk/historical-stress?ticker=AAPL');
        researchRequest.mockRejectedValue(new AppError('503', 'RESEARCH_API_ERROR', 503));
        await expect(getHistoricalStress()).rejects.toMatchObject({ code: 'RESEARCH_API_ERROR', statusCode: 503 });
        researchRequest.mockRejectedValue(new ExternalAPIError('red', 'research'));
        await expect(getHistoricalStress()).rejects.toMatchObject({ code: 'EXTERNAL_API_ERROR' });
    });
});

describe('corporate-actions', () => {
    it('apply con id no finito -> error antes de llamar', async () => {
        await expect(applyCorporateAction(Number.NaN)).rejects.toThrow('inválido');
        expect(researchRequest).not.toHaveBeenCalled();
        await applyCorporateAction(7);
        expect(researchRequest).toHaveBeenCalledWith('/api/corporate-actions/7/apply', { method: 'POST' });
    });

    it('sync-status caído -> null (no rompe la página)', async () => {
        researchRequest.mockRejectedValue(new Error('500'));
        expect(await getCorporateActionsSyncStatus()).toBeNull();
        researchRequest.mockResolvedValue([]);
        expect(await getCorporateActions()).toEqual([]);
    });
});

describe('catalysts', () => {
    it('followed: solo fechas ISO válidas entran en la query', async () => {
        await getFollowedEarnings({ desde: '2026-11-01', hasta: 'no-fecha' });
        expect(String(researchRequest.mock.calls[0][0])).toBe('/api/calendar/followed?desde=2026-11-01');
        await getFollowedEarnings({ desde: '2026-1-1' });
        expect(String(researchRequest.mock.calls[1][0])).toBe('/api/calendar/followed');
        await getFollowedEarnings();
        expect(String(researchRequest.mock.calls[2][0])).toBe('/api/calendar/followed');
        await getCatalystCalendar();
        expect(String(researchRequest.mock.calls[3][0])).toBe('/api/calendar/catalysts');
    });
});

describe('risk y share-capital', () => {
    it('rutas directas con ticker codificado', async () => {
        await getRiskDashboard();
        expect(researchRequest).toHaveBeenCalledWith('/api/risk/dashboard');
        await getShareCapital('BRK.B');
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/BRK.B/share-capital', { fast: true });
    });
});

describe('portfolio-image', () => {
    it('imagen vacía o de más de 2 MB -> error antes de llamar', async () => {
        expect(await previewPortfolioImage('')).toEqual({ ok: false, error: expect.stringContaining('2 MB') });
        expect(await previewPortfolioImage('x'.repeat(2_796_205))).toEqual({ ok: false, error: expect.stringContaining('2 MB') });
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('preview y review van al backend con su timeout', async () => {
        researchRequest.mockResolvedValue({ status: 'preview' });
        await previewPortfolioImage('aW1hZ2Vu');
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/image/preview', { method: 'POST', body: JSON.stringify({ image_base64: 'aW1hZ2Vu' }), timeoutMs: 20000 });
        await reviewPortfolioImage('hash', []);
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/image/review', { method: 'POST', body: JSON.stringify({ image_hash: 'hash', rows: [] }), timeoutMs: 30000 });
    });

    it('los motivos del backend (422/503, en español) vuelven como dato: Next los ocultaría en prod si se lanzaran', async () => {
        researchRequest.mockRejectedValueOnce(new AppError('Usa una imagen PNG, JPEG o WebP sin animación', 'RESEARCH_API_ERROR', 422));
        expect(await previewPortfolioImage('aW1hZ2Vu')).toEqual({ ok: false, error: 'Usa una imagen PNG, JPEG o WebP sin animación' });
        researchRequest.mockRejectedValueOnce(new AppError('Hay otra captura en lectura. Vuelve a intentarlo en unos segundos', 'RESEARCH_API_ERROR', 503));
        expect(await previewPortfolioImage('aW1hZ2Vu')).toEqual({ ok: false, error: expect.stringMatching(/^Hay otra captura/) });
        researchRequest.mockRejectedValueOnce(new AppError('Cotización caducada. Vuelve a revisar', 'RESEARCH_API_ERROR', 422));
        expect(await confirmPortfolioImage(9)).toEqual({ ok: false, error: 'Cotización caducada. Vuelve a revisar' });
        expect(requestCacheInvalidate).not.toHaveBeenCalled();
        researchRequest.mockRejectedValueOnce(new AppError('Rate limit exceeded', 'RESEARCH_API_ERROR', 429));
        expect(await searchImageInstrument('ASTS')).toEqual({ ok: false, error: expect.stringMatching(/^Demasiadas peticiones/) });
    });

    it('búsqueda de instrumento acotada a 80 caracteres', async () => {
        researchRequest.mockResolvedValue([]);
        await searchImageInstrument('a'.repeat(200));
        expect(String(researchRequest.mock.calls[0][0])).toContain(`q=${'a'.repeat(80)}`);
    });

    it('confirm invalida las 7 lecturas de cartera del usuario', async () => {
        researchRequest.mockResolvedValue({ status: 'ok', positions_imported: 4 });
        expect(await confirmPortfolioImage(9)).toMatchObject({ ok: true, data: { positions_imported: 4 } });
        for (const suffix of ['positions', 'summary', 'transactions', 'scores', 'tearsheet', 'dividends', 'quality']) {
            expect(requestCacheInvalidate).toHaveBeenCalledWith(`portfolio:user-1:${suffix}`);
        }
    });
});

describe('portfolio-settings', () => {
    it('lectura no-store; cambio de base revalida cartera y ajustes', async () => {
        await getPortfolioCurrencySettings();
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/configuration', { cache: 'no-store' });
        await savePortfolioBaseCurrency('USD');
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/configuration', { method: 'PUT', body: JSON.stringify({ base_currency: 'USD' }) });
        expect(revalidatePath).toHaveBeenCalledWith('/portfolio');
        expect(revalidatePath).toHaveBeenCalledWith('/settings');
    });
});

describe('ticker-context: ningún badge es una afirmación falsa', () => {
    // Contrato REAL: la watchlist se lee con el wrapper verdadero
    // (getWatchlistState) y solo se mockea HTTP (researchRequest) y auth. El
    // wrapper captura los fallos y devuelve { items: [], unavailable: true }:
    // availability.watchlist debe mirar ese flag, no una excepción.
    const positionsOk = [{ ticker: 'aapl', quantity: 10 }];
    const http = (positions: unknown, watchlist: unknown) =>
        researchRequest.mockImplementation(async (url: string) => {
            if (url.startsWith('/api/watchlist')) {
                if (watchlist instanceof Error) throw watchlist;
                return watchlist;
            }
            if (positions instanceof Error) throw positions;
            return positions;
        });

    it('posición abierta (incl. corta) lleva badge; quantity 0 o null NO', async () => {
        http([
            { ticker: 'aapl', quantity: 10 },
            { ticker: 'cerrada', quantity: 0 },
            { ticker: 'sinqty', quantity: null },
            { ticker: 'corta', quantity: -3 },
        ], [{ symbol: 'meta' }]);
        const ctx = await getTickerContext();
        expect(ctx.portfolioTickers).toEqual(['AAPL', 'CORTA']);
        expect(ctx.watchlistTickers).toEqual(['META']);
        expect(ctx.availability).toEqual({ portfolio: true, watchlist: true });
    });

    it('pide posiciones con page_size=200 (el backend pagina; sin parametro solo llegaban 20)', async () => {
        http({ items: [{ ticker: 'aapl', quantity: 10 }] }, []);
        const ctx = await getTickerContext();
        expect(ctx.portfolioTickers).toEqual(['AAPL']);
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/positions?page=1&page_size=200', { fast: true });
    });

    it('TODO caído -> conjuntos vacíos, nunca inventados, availability false/false', async () => {
        http(new Error('500'), new Error('500'));
        expect(await getTickerContext()).toEqual({
            portfolioTickers: [],
            watchlistTickers: [],
            availability: { portfolio: false, watchlist: false },
        });
    });

    it('watchlist caída SIN lanzar (contrato real): availability.watchlist=false aunque items=[]', async () => {
        // Regresión #5347: con el wrapper aplanador, Promise.allSettled la
        // marcaba disponible y «Para ti» mostraba el vacío normal.
        http(positionsOk, new Error('500'));
        const ctx = await getTickerContext();
        expect(ctx.portfolioTickers).toEqual(['AAPL']);
        expect(ctx.watchlistTickers).toEqual([]);
        expect(ctx.availability).toEqual({ portfolio: true, watchlist: false });
    });

    it('respuesta de watchlist que no es array también cuenta como caída', async () => {
        http(positionsOk, { oops: true });
        const ctx = await getTickerContext();
        expect(ctx.availability).toEqual({ portfolio: true, watchlist: false });
    });

    it('posiciones caídas -> availability.portfolio=false y watchlist intacta', async () => {
        http(new Error('500'), [{ symbol: 'meta' }]);
        const ctx = await getTickerContext();
        expect(ctx.portfolioTickers).toEqual([]);
        expect(ctx.watchlistTickers).toEqual(['META']);
        expect(ctx.availability).toEqual({ portfolio: false, watchlist: true });
    });
});
