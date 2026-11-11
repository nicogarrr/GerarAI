import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * NewsFeedSection (/research/news): carriles, paginación y degradación. El
 * carril «Para ti» sin empresas seguidas NO llama al backend (NO FAV PR
 * #1753); la página pide NEWS_PAGE_SIZE+1 para saber si hay siguiente; solo la
 * caída reconocida del backend degrada a pantalla de reintento conservando
 * carril, ticker y página.
 */
vi.mock('@/lib/i18n/server', () => ({ getT: async () => (key: string) => key }));
vi.mock('@/lib/actions/ticker-context.actions', () => ({ getTickerContext: vi.fn() }));
const getResearchNews = vi.fn();
vi.mock('@/lib/actions/research.actions', () => ({ getResearchNews: (...a: unknown[]) => getResearchNews(...a) }));
const isBackendUnavailableError = vi.fn();
vi.mock('@/lib/backend-offline', () => ({ isBackendUnavailableError: (e: unknown) => isBackendUnavailableError(e) }));

let flowProps: Record<string, unknown> = {};
vi.mock('@/components/research/NewsEventsFlow', () => ({
    NewsEventsFlow: (props: Record<string, unknown>) => {
        flowProps = props;
        return null;
    },
}));
let offlineProps: Record<string, unknown> = {};
vi.mock('@/components/system/BackendOffline', () => ({
    default: (props: Record<string, unknown>) => {
        offlineProps = props;
        return null;
    },
}));

import { NewsFeedSection } from '@/app/(root)/research/news/NewsFeedSection';
import { NEWS_PAGE_SIZE } from '@/lib/news-paging';

type Availability = { portfolio: boolean; watchlist: boolean };
const context = (
    portfolioTickers: string[],
    watchlistTickers: string[],
    availability: Availability = { portfolio: true, watchlist: true },
) => Promise.resolve({ portfolioTickers, watchlistTickers, availability });
const event = (n: number) => ({ title: `Noticia ${n}`, url: `https://medio.example/n${n}` });
const feed = (n: number) => Array.from({ length: n }, (_, i) => event(i + 1));

beforeEach(() => {
    flowProps = {};
    offlineProps = {};
    getResearchNews.mockReset();
    isBackendUnavailableError.mockReset();
});

describe('NewsFeedSection', () => {
    it('«Para ti» sin cartera ni watchlist: estado vacío SIN llamar al backend', async () => {
        render(await NewsFeedSection({ lane: 'para-ti', ticker: null, page: 1, tickerContextPromise: context([], []) }));
        expect(getResearchNews).not.toHaveBeenCalled();
        expect(flowProps.events).toEqual([]);
        expect(flowProps.hasMore).toBe(false);
    });

    it('«Para ti» con seguidas: une cartera y watchlist sin duplicar y los manda al backend', async () => {
        getResearchNews.mockResolvedValue(feed(3));
        render(await NewsFeedSection({ lane: 'para-ti', ticker: null, page: 1, tickerContextPromise: context(['KO', 'AAPL'], ['AAPL', 'MSFT']) }));
        expect(getResearchNews).toHaveBeenCalledWith('para-ti', 0, NEWS_PAGE_SIZE + 1, null, ['KO', 'AAPL', 'MSFT']);
    });

    it('pide uno de más y recorta: hasMore solo cuando llegan PAGE_SIZE+1', async () => {
        getResearchNews.mockResolvedValue(feed(NEWS_PAGE_SIZE + 1));
        render(await NewsFeedSection({ lane: 'macro', ticker: null, page: 3, tickerContextPromise: context([], []) }));
        expect(getResearchNews).toHaveBeenCalledWith('macro', 2 * NEWS_PAGE_SIZE, NEWS_PAGE_SIZE + 1, null, []);
        expect(flowProps.hasMore).toBe(true);
        expect((flowProps.events as unknown[]).length).toBe(NEWS_PAGE_SIZE);

        getResearchNews.mockResolvedValue(feed(NEWS_PAGE_SIZE));
        render(await NewsFeedSection({ lane: 'macro', ticker: null, page: 1, tickerContextPromise: context([], []) }));
        expect(flowProps.hasMore).toBe(false);
    });

    it('deduplica el recorte por identidad de titular/URL conservando la primera aparición', async () => {
        getResearchNews.mockResolvedValue([event(1), event(1), event(2)]);
        render(await NewsFeedSection({ lane: null, ticker: null, page: 1, tickerContextPromise: context([], []) }));
        expect((flowProps.events as unknown[]).length).toBe(2);
    });

    it('backend caído: reintento conservando carril, ticker y página (>1)', async () => {
        getResearchNews.mockRejectedValue(new Error('connection refused'));
        isBackendUnavailableError.mockReturnValue(true);
        render(await NewsFeedSection({ lane: 'macro', ticker: 'AAPL', page: 2, tickerContextPromise: context(['KO'], []) }));
        expect(offlineProps.retryHref).toBe('/research/news?lane=macro&ticker=AAPL&pagina=2');
    });

    it('backend caído en la primera página sin filtros: reintento desnudo', async () => {
        getResearchNews.mockRejectedValue(new Error('connection refused'));
        isBackendUnavailableError.mockReturnValue(true);
        render(await NewsFeedSection({ lane: null, ticker: null, page: 1, tickerContextPromise: context([], []) }));
        expect(offlineProps.retryHref).toBe('/research/news');
    });

    it('«Para ti» con AMBAS lecturas caídas: error con reintento, no el vacío normal, y no llama al backend', async () => {
        const { getByText, getByRole } = render(await NewsFeedSection({
            lane: 'para-ti', ticker: null, page: 1,
            tickerContextPromise: context([], [], { portfolio: false, watchlist: false }),
        }));
        expect(getResearchNews).not.toHaveBeenCalled();
        // Sin feed y sin el empty state «sin empresas»: sería una afirmación falsa.
        expect(flowProps.events).toBeUndefined();
        getByText('research.newsContextErrorTitle');
        expect(getByRole('link', { name: /common.actions.retry/ })).toHaveAttribute('href', '/research/news?lane=para-ti');
    });

    it('«Para ti» con UNA lectura caída y cero tickers disponibles: aviso + reintento, sin feed ni vacío', async () => {
        const { getByText, getByRole, queryByText } = render(await NewsFeedSection({
            lane: 'para-ti', ticker: null, page: 2,
            tickerContextPromise: context([], [], { portfolio: false, watchlist: true }),
        }));
        expect(getResearchNews).not.toHaveBeenCalled();
        expect(flowProps.events).toBeUndefined();
        // El error nombra SOLO la fuente caída, no «cartera ni watchlist».
        getByText('research.newsContextPartialErrorTitle');
        getByText('research.newsContextPartialErrorBody');
        expect(queryByText('research.newsContextErrorTitle')).toBeNull();
        expect(queryByText('research.flow.emptyForYouTitle')).toBeNull();
        expect(getByRole('link', { name: /common.actions.retry/ })).toHaveAttribute('href', '/research/news?lane=para-ti&pagina=2');
    });

    it('«Para ti» con UNA lectura caída pero tickers disponibles: feed con aviso de contexto parcial y reintento', async () => {
        getResearchNews.mockResolvedValue(feed(2));
        const { getByText, getByRole } = render(await NewsFeedSection({
            lane: 'para-ti', ticker: null, page: 1,
            tickerContextPromise: context(['KO'], [], { portfolio: true, watchlist: false }),
        }));
        expect(getResearchNews).toHaveBeenCalledWith('para-ti', 0, NEWS_PAGE_SIZE + 1, null, ['KO']);
        expect((flowProps.events as unknown[]).length).toBe(2);
        getByText('research.newsContextPartial');
        expect(getByRole('link', { name: /common.actions.retry/ })).toHaveAttribute('href', '/research/news?lane=para-ti');
    });

    it('otros carriles: el contexto caído solo apaga badges, el feed sigue normal', async () => {
        getResearchNews.mockResolvedValue(feed(2));
        const { queryByText } = render(await NewsFeedSection({
            lane: 'macro', ticker: null, page: 1,
            tickerContextPromise: context([], [], { portfolio: false, watchlist: false }),
        }));
        expect(getResearchNews).toHaveBeenCalledWith('macro', 0, NEWS_PAGE_SIZE + 1, null, []);
        expect(flowProps.portfolioTickers).toEqual([]);
        expect(queryByText('research.newsContextPartial')).toBeNull();
    });

    it('error que no es caída del backend se propaga, no se disfraza', async () => {
        getResearchNews.mockRejectedValue(new Error('boom 500'));
        isBackendUnavailableError.mockReturnValue(false);
        await expect(
            NewsFeedSection({ lane: null, ticker: null, page: 1, tickerContextPromise: context([], []) }),
        ).rejects.toThrow('boom 500');
    });
});
