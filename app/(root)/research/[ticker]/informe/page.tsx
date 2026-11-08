import type { Metadata } from 'next';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import PrintButton from '@/components/research/PrintButton';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getDcaWatchCard } from '@/lib/actions/dca-watch-card.actions';
import { getPublicShorts } from '@/lib/actions/public-shorts.actions';
import { getResearchValuationWorkspace } from '@/lib/actions/research.actions';
import { getValuationSummaries } from '@/lib/actions/valuation-summary.actions';
import { engineRangeFrom, getAnalystReport, getPublishedThesis, type ReportInputs } from '@/lib/research/analyst-report';
import { getFormat, getLocale, getT } from '@/lib/i18n/server';
import { getKeyStats } from '@/lib/research/key-stats';
import { getSotp } from '@/lib/research/sotp';
import { impliedGrowthText, sbcAdjustmentText, trackRecordText } from '@/lib/research/valuation-method';
import { baseRateText } from '@/lib/research/valuation-summary';

export const dynamic = 'force-dynamic';

export async function generateMetadata({ params }: { params: Promise<{ ticker: string }> }): Promise<Metadata> {
  const t = await getT();
  return { title: t('research.informe.metaTitle', { ticker: (await params).ticker.toUpperCase() }) };
}

/**
 * «Informe» tipo nota de analista de cualquier empresa (pedido de Nico,
 * 8-nov-2026). Solo lee APIs existentes en paralelo; cada pieza que falle sale
 * vacía con su motivo y el resto del informe se pinta. Imprimible: la clase
 * `print-document` (app/globals.css) quita el chrome y pone papel blanco.
 */
export default async function InformePage({ params }: { params: Promise<{ ticker: string }> }) {
  await requireAuthenticatedUser();
  const ticker = (await params).ticker.toUpperCase();
  const [t, fmt, locale] = await Promise.all([getT(), getFormat(), getLocale()]);
  const [report, card, summaries, thesis, sotp, valuation, keyStats, shorts] = await Promise.all([
    getAnalystReport(ticker),
    getDcaWatchCard(ticker),
    getValuationSummaries([ticker]).catch(() => ({} as Awaited<ReturnType<typeof getValuationSummaries>>)),
    getPublishedThesis(ticker),
    getSotp(ticker),
    getResearchValuationWorkspace(ticker).catch(() => null),
    getKeyStats(ticker),
    getPublicShorts(ticker).catch(() => null),
  ]);
  const summary = summaries[ticker] ?? null;
  const data: ReportInputs = {
    ticker,
    report,
    card,
    fair: summary?.fair_value ?? null,
    thesis,
    sotp,
    engineRange: engineRangeFrom(valuation?.fair_value_range as Record<string, unknown> | null | undefined),
    keyStats,
    shorts,
    honesty: {
      trackRecord: trackRecordText(valuation?.track_record, locale),
      sbc: sbcAdjustmentText(valuation?.sbc_adjustment, locale),
      baseRate: baseRateText(summary?.base_rate, locale),
      impliedGrowth: impliedGrowthText(valuation?.implied_growth, locale),
    },
    today: new Date().toISOString().slice(0, 10),
  };
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-4xl flex-col gap-3">
      <div className="flex justify-end print:hidden"><PrintButton /></div>
      <AnalystReportView data={data} t={t} fmt={fmt} locale={locale} />
    </main>
  );
}
