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

export const metadata: Metadata = { title: 'Noticias' };

export default async function ResearchNewsPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const lane = query.lane === 'macro' || query.lane === 'empresa' || query.lane === 'para-ti' ? query.lane : null;
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
  const fetched =
    lane === 'para-ti' && paraTiTickers.length === 0
      ? []
      : await getResearchNews(
          lane,
          (page - 1) * NEWS_PAGE_SIZE,
          NEWS_PAGE_SIZE + 1,
          ticker,
          paraTiTickers,
        );
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
              {ticker ? `Volver a ${ticker}` : 'Research'}
            </Link>
          </Button>
        }
        kicker="Inteligencia de mercado"
        title="Eventos de noticias"
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
        <summary className="cursor-pointer font-semibold text-gray-300">Añadir noticias</summary>
        <div className="mt-4 grid gap-6">
      <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Analizar un artículo</h2>
        </div>
        <MutationForm action={submitAnalyzeNews} className="grid gap-3" resetOnSuccess successMessage="Noticia analizada">
          <div className="grid gap-2">
            <label className="text-sm font-semibold text-gray-400" htmlFor="text">
              Texto de la noticia
            </label>
            <Textarea
              className="min-h-[160px] border-gray-800 bg-black/30 text-gray-200 focus-visible:ring-teal-500"
              id="text"
              name="text"
              placeholder="Pega aquí el artículo, la nota de prensa o la nota de relaciones con inversores..."
              required
            />
          </div>
          <div className="grid gap-2 sm:grid-cols-[160px_1fr] sm:items-center">
            <label className="text-sm font-semibold text-gray-400" htmlFor="source">
              Fuente
            </label>
            <Input id="source" name="source" placeholder="Bloomberg, FT, RI..." />
          </div>
          <div className="grid gap-2 sm:grid-cols-[160px_1fr] sm:items-center">
            <label className="text-sm font-semibold text-gray-400" htmlFor="url">
              URL de la fuente
            </label>
            <Input id="url" name="url" placeholder="https://..." type="url" />
          </div>
          <Button className="w-full sm:w-fit" type="submit">
            Analizar noticia
          </Button>
        </MutationForm>
      </section>

      <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Importar noticias en lote</h2>
        </div>
        <MutationForm action={submitIngestFeed} className="grid gap-3" resetOnSuccess successMessage="Noticias importadas">
          <div className="grid gap-2 sm:grid-cols-[160px_1fr] sm:items-center">
            <label className="text-sm font-semibold text-gray-400" htmlFor="feed-source">
              Fuente
            </label>
            <Input defaultValue="manual_feed" id="feed-source" name="source" />
          </div>
          <Textarea
            className="min-h-[180px] border-gray-800 bg-black/30 font-mono text-xs text-gray-200 focus-visible:ring-teal-500"
            name="items"
            placeholder='[{"ticker":"MSFT","title":"MSFT recorta guía","text":"resultado por debajo y recorte de guía","url":"https://..."}]'
            required
          />
          <Button className="w-full sm:w-fit" type="submit" variant="outline">
            Importar lote
          </Button>
        </MutationForm>
      </section>
        </div>
      </details>
    </main>
  );
}
