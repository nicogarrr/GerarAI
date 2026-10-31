import type { Metadata } from 'next';
import { AlertTriangle, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { Textarea } from '@/components/ui/textarea';
import { MutationForm } from '@/components/forms/MutationForm';
import { dedupeNewsEvents } from '@/lib/news-display';
import { analyzeManualNews, getResearchNews, ingestResearchNewsFeed } from '@/lib/actions/research.actions';
import { NewsEventsFlow } from '@/components/research/NewsEventsFlow';
import { NEWS_PAGE_SIZE } from '@/lib/news-paging';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';
import BackendOffline from '@/components/system/BackendOffline';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

async function submitAnalyzeNews(formData: FormData): Promise<void> {
  'use server';
  await analyzeManualNews(formData);
}

async function submitIngestFeed(formData: FormData): Promise<void> {
  'use server';
  await ingestResearchNewsFeed(formData);
}

type PageProps = { searchParams: Promise<{ lane?: string; pagina?: string; ticker?: string }> };

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('research.newsMetaTitle') };
}

export default async function ResearchNewsPage({ searchParams }: PageProps) {
  const t = await getT();
  const query = await searchParams;
  const lane = query.lane === 'macro' || query.lane === 'empresa' || query.lane === 'para-ti' || query.lane === 'gobierno' ? query.lane : null;
  const ticker = query.ticker?.trim().toUpperCase() || null;
  const parsed = Number.parseInt(query.pagina ?? '1', 10);
  const page = Number.isFinite(parsed) ? Math.min(Math.max(1, parsed), 1000) : 1;
  // Se pide uno de más para saber si hay página siguiente sin contar toda la tabla.
  const tickerContextPromise = getTickerContext();
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
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
      <PageHeader
        back={
          <Button asChild size="sm" variant="ghost">
            <Link href={ticker ? `/research/${encodeURIComponent(ticker)}` : '/research'}>
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              {ticker ? t('research.backToTicker', { ticker }) : 'Research'}
            </Link>
          </Button>
        }
        kicker={t('research.newsKicker')}
        title={t('research.newsTitle')}
      />

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

      <details className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <summary className="min-h-11 cursor-pointer py-2.5 font-semibold text-gray-300">{t('research.newsAdd')}</summary>
        <div className="mt-4 grid gap-6">
      <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('research.analyzeTitle')}</h2>
        </div>
        <MutationForm action={submitAnalyzeNews} className="grid gap-3" resetOnSuccess successMessage={t('research.analyzeSuccess')}>
          <div className="grid gap-2">
            <label className="text-sm font-semibold text-gray-400" htmlFor="text">
              {t('research.analyzeTextLabel')}
            </label>
            <Textarea
              className="min-h-[160px] border-gray-800 bg-black/30 text-gray-200 focus-visible:ring-teal-500"
              id="text"
              name="text"
              placeholder={t('research.analyzeTextPlaceholder')}
              required
            />
          </div>
          <div className="grid gap-2 sm:grid-cols-[160px_1fr] sm:items-center">
            <label className="text-sm font-semibold text-gray-400" htmlFor="source">
              {t('research.sourceLabel')}
            </label>
            <Input className="min-h-11" id="source" name="source" placeholder={t('research.sourcePlaceholder')} />
          </div>
          <div className="grid gap-2 sm:grid-cols-[160px_1fr] sm:items-center">
            <label className="text-sm font-semibold text-gray-400" htmlFor="url">
              {t('research.sourceUrlLabel')}
            </label>
            <Input className="min-h-11" id="url" name="url" placeholder="https://..." type="url" />
          </div>
          <Button className="w-full sm:w-fit" type="submit">
            {t('research.analyzeSubmit')}
          </Button>
        </MutationForm>
      </section>

      <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('research.ingestTitle')}</h2>
        </div>
        <MutationForm action={submitIngestFeed} className="grid gap-3" resetOnSuccess successMessage={t('research.ingestSuccess')}>
          <div className="grid gap-2 sm:grid-cols-[160px_1fr] sm:items-center">
            <label className="text-sm font-semibold text-gray-400" htmlFor="feed-source">
              {t('research.sourceLabel')}
            </label>
            <Input className="min-h-11" defaultValue="manual_feed" id="feed-source" name="source" />
          </div>
          <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.ingestItemsLabel')}</span><Textarea
            className="min-h-[180px] border-gray-800 bg-black/30 font-mono text-base text-gray-200 focus-visible:ring-teal-500 md:text-xs"
            name="items"
            placeholder={t('research.ingestItemsPlaceholder')}
            required
          /></label>
          <Button className="w-full sm:w-fit" type="submit" variant="outline">
            {t('research.ingestSubmit')}
          </Button>
        </MutationForm>
      </section>
        </div>
      </details>
    </main>
  );
}
