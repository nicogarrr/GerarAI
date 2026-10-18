import type { Metadata } from 'next';
import { AssistantRedirect } from '@/components/research/AssistantRedirect';

export const metadata: Metadata = { title: 'Asistente de investigación', description: 'La guía de investigación vive en el Cerebro.' };

const TICKER_RE = /^[A-Z0-9.\-]{1,20}$/;

/**
 * La página del asistente ya no existe como tal: se unificó en el Cerebro.
 * Esta ruta queda como redirect de compatibilidad que abre el Cerebro con el
 * ticker (y la revisión anclada, si venía) vía handoff de sessionStorage.
 */
export default async function ResearchAssistantPage({ searchParams }: {
  searchParams: Promise<{ ticker?: string | string[]; review_id?: string | string[] }>;
}) {
  const params = await searchParams;
  const rawTicker = Array.isArray(params.ticker) ? params.ticker[0] : params.ticker;
  const ticker = rawTicker?.trim().toUpperCase();
  const validTicker = ticker && TICKER_RE.test(ticker) ? ticker : undefined;
  const rawReview = Array.isArray(params.review_id) ? params.review_id[0] : params.review_id;
  const reviewId = rawReview && /^[1-9]\d*$/.test(rawReview) && Number.isSafeInteger(Number(rawReview)) ? Number(rawReview) : undefined;
  return <AssistantRedirect ticker={validTicker} reviewId={reviewId} />;
}
