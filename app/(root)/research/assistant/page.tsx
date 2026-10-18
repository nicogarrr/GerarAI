import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import ResearchAssistant from '@/components/research/ResearchAssistant';

export const metadata: Metadata = { title: 'Asistente de investigación', description: 'Explora y guía tu investigación con fuentes; solo lectura.' };

export default async function ResearchAssistantPage({ searchParams }: {
  searchParams: Promise<{ ticker?: string | string[]; review_id?: string | string[]; mode?: string | string[] }>;
}) {
  const params = await searchParams;
  const rawTicker = Array.isArray(params.ticker) ? params.ticker[0] : params.ticker;
  const ticker = rawTicker?.trim().toUpperCase() || undefined;
  const rawReview = Array.isArray(params.review_id) ? params.review_id[0] : params.review_id;
  const reviewId = rawReview && /^[1-9]\d*$/.test(rawReview) && Number.isSafeInteger(Number(rawReview)) ? Number(rawReview) : undefined;
  const mode = (Array.isArray(params.mode) ? params.mode[0] : params.mode) === 'guide' && ticker ? 'guide' : 'explore';
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-1 py-4 sm:px-4 sm:py-6">
      <header className="border-b border-gray-800 pb-5">
        <Link href={ticker ? `/research/${encodeURIComponent(ticker)}` : '/research'} className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm text-gray-400 hover:text-teal-300"><ArrowLeft aria-hidden className="h-4 w-4" />Research</Link>
        <p className="text-sm font-semibold uppercase text-teal-300">Research · solo lectura</p>
        <h1 className="mt-1 text-2xl font-bold text-gray-100 sm:text-3xl">Asistente de investigación</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">Explora una pregunta o guía el análisis de una empresa. Solo lectura: no acepta conclusiones ni modifica nada.</p>
      </header>
      <ResearchAssistant initialMode={mode} initialTicker={ticker} initialReviewId={reviewId} />
    </main>
  );
}
