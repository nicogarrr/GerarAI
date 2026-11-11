import { Suspense } from 'react';
import type { Metadata } from 'next';
import { AlertTriangle, ArrowLeft } from 'lucide-react';
import { HistoryBackLink } from '@/components/common/HistoryBackLink';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { Textarea } from '@/components/ui/textarea';
import { MutationForm } from '@/components/forms/MutationForm';
import { analyzeManualNews, ingestResearchNewsFeed } from '@/lib/actions/research.actions';
import { NewsFeedSection } from './NewsFeedSection';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';
import { NewsLoadingSkeleton } from '@/components/LoadingState';
import { getT } from '@/lib/i18n/server';
import { i18nPageTitle } from '@/lib/i18n/metadata';

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
    return i18nPageTitle('research.newsMetaTitle');
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

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
      <PageHeader
        back={
          <Button asChild size="sm" variant="ghost">
            <HistoryBackLink href={ticker ? `/research/${encodeURIComponent(ticker)}` : '/research'}>
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              {ticker ? t('research.backToTicker', { ticker }) : 'Research'}
            </HistoryBackLink>
          </Button>
        }
        kicker={t('research.newsKicker')}
        title={t('research.newsTitle')}
      />

      <Suspense fallback={<NewsLoadingSkeleton />}>
        <NewsFeedSection lane={lane} page={page} ticker={ticker} tickerContextPromise={tickerContextPromise} />
      </Suspense>

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
