import Link from 'next/link';
import { RefreshCcw } from 'lucide-react';

import BackendOffline from '@/components/system/BackendOffline';
import { Button } from '@/components/ui/button';
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
  const retryParams = new URLSearchParams();
  if (lane) retryParams.set('lane', lane);
  if (ticker) retryParams.set('ticker', ticker);
  if (page > 1) retryParams.set('pagina', String(page));
  const retryQuery = retryParams.toString();
  const retryHref = retryQuery ? `/research/news?${retryQuery}` : '/research/news';

  // Carril «Para ti»: solo empresas de la cartera y la watchlist del usuario
  // (relevancia por contexto; el backend recibe los tickers explícitos). En el
  // resto de carriles el contexto se resuelve en paralelo con el feed.
  let paraTiTickers: string[] = [];
  let contextWarning: 'partial' | 'total' | null = null;
  let failedSource: 'portfolio' | 'watchlist' | null = null;
  if (lane === 'para-ti') {
    const awaitedContext = await tickerContextPromise;
    const { availability } = awaitedContext;
    if (!availability.portfolio && !availability.watchlist) {
      contextWarning = 'total';
    } else if (!availability.portfolio || !availability.watchlist) {
      contextWarning = 'partial';
      failedSource = availability.portfolio ? 'watchlist' : 'portfolio';
    }
    paraTiTickers = [...new Set([...awaitedContext.portfolioTickers, ...awaitedContext.watchlistTickers])];
  }
  // Fallo total del contexto: no hay forma honesta de elegir «Para ti»; error
  // con reintento, NUNCA el estado vacío normal (que afirmaría «no sigues
  // ninguna empresa»). Fallo parcial con cero tickers disponibles: igualmente
  // no se puede afirmar el vacío — aviso + reintento sin feed.
  if (contextWarning === 'total' || (contextWarning === 'partial' && paraTiTickers.length === 0)) {
    return (
      <section className="mx-auto flex w-full max-w-2xl flex-col items-center gap-4 px-4 py-16 text-center">
        <h2 className="text-xl font-bold text-gray-100">{t('research.newsContextErrorTitle')}</h2>
        <p className="max-w-md text-sm leading-6 text-gray-400">{t('research.newsContextErrorBody')}</p>
        <Button asChild className="min-h-[44px] px-6">
          <Link href={retryHref}>
            <RefreshCcw aria-hidden="true" className="h-4 w-4" />
            {t('common.actions.retry')}
          </Link>
        </Button>
      </section>
    );
  }
  // Sin empresas en cartera ni watchlist (ambas lecturas OK) no hay nada que
  // filtrar: estado vacío sin llamar al backend (NO FAV auditoría PR #1753).
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
      return <BackendOffline feature={t('research.newsFeature')} retryHref={retryHref} />;
    }
    throw error;
  }
  const tickerContext = await tickerContextPromise;
  const hasMore = fetched.length > NEWS_PAGE_SIZE;
  const events = dedupeNewsEvents(fetched.slice(0, NEWS_PAGE_SIZE));


  return (
    <>
      {contextWarning === 'partial' && failedSource !== null ? (
        <div role="status" className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          <span className="min-w-0 flex-1">
            {t('research.newsContextPartial', { source: t(failedSource === 'portfolio' ? 'research.newsContextSourcePortfolio' : 'research.newsContextSourceWatchlist') })}
          </span>
          <Link href={retryHref} className="inline-flex min-h-[44px] shrink-0 items-center gap-1 underline underline-offset-2">
            <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" />
            {t('common.actions.retry')}
          </Link>
        </div>
      ) : null}
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
    </>
  );
}
