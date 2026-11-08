import BackendOffline from '@/components/system/BackendOffline';
import { NewsEventsFlow } from '@/components/research/NewsEventsFlow';
import { getResearchNews } from '@/lib/actions/research.actions';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT } from '@/lib/i18n/server';
import { dedupeNewsEvents } from '@/lib/news-display';
import { NEWS_PAGE_SIZE } from '@/lib/news-paging';

// Extraído de page.tsx (8-nov-2026): Next solo admite los exports propios de
// página en page.tsx; el componente vive aquí para poder probarlo directo.
export async function NewsFeedSection({ lane, ticker, page, tickerContextPromise }: {
  lane: 'macro' | 'empresa' | 'para-ti' | 'gobierno' | null;
  ticker: string | null;
  page: number;
  tickerContextPromise: ReturnType<typeof getTickerContext>;
}) {
  const t = await getT();
  // Carril «Para ti»: solo empresas de la cartera y la watchlist del usuario
  // (relevancia por contexto; el backend recibe los tickers explícitos). En el
  // resto de carriles el contexto se resuelve en paralelo con el feed.
  let paraTiTickers: string[] = [];
  if (lane === 'para-ti') {
    const awaitedContext = await tickerContextPromise;
    paraTiTickers = [...new Set([...awaitedContext.portfolioTickers, ...awaitedContext.watchlistTickers])];
  }
  // Sin empresas en cartera ni watchlist no hay nada que filtrar: estado vacío
  // sin llamar al backend (NO FAV auditoría PR #1753).
  // Solo la caída reconocida del backend (red o 5xx) degrada a BackendOffline;
  // auth, 4xx y errores de programación siguen al error boundary de la ruta.
  let fetched: Awaited<ReturnType<typeof getResearchNews>>;
  try {
    fetched =
      lane === 'para-ti' && paraTiTickers.length === 0
        ? []
        : await getResearchNews(
            lane,
            (page - 1) * NEWS_PAGE_SIZE,
            NEWS_PAGE_SIZE + 1,
            ticker,
            paraTiTickers,
          );
  } catch (error) {
    // Con salida temprana la promesa del contexto quedaría sin consumir.
    tickerContextPromise.catch(() => undefined);
    if (isBackendUnavailableError(error)) {
      const retryParams = new URLSearchParams();
      if (lane) retryParams.set('lane', lane);
      if (ticker) retryParams.set('ticker', ticker);
      if (page > 1) retryParams.set('pagina', String(page));
      const retryQuery = retryParams.toString();
      return <BackendOffline feature={t('research.newsFeature')} retryHref={retryQuery ? `/research/news?${retryQuery}` : '/research/news'} />;
    }
    throw error;
  }
  const tickerContext = await tickerContextPromise;
  const hasMore = fetched.length > NEWS_PAGE_SIZE;
  const events = dedupeNewsEvents(fetched.slice(0, NEWS_PAGE_SIZE));


  return (
    <NewsEventsFlow
        events={events}
        hasMore={hasMore}
        key={`${lane ?? 'todas'}-${ticker ?? 'todos'}-${page}`}
        lane={lane}
        page={page}
        ticker={ticker}
        portfolioTickers={tickerContext.portfolioTickers}
        watchlistTickers={tickerContext.watchlistTickers}
      />

  );
}
