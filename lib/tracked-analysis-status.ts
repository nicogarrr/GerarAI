// @ts-expect-error TS5097
import { DEFAULT_LOCALE, type Locale } from './i18n/locale.ts';
import type { TranslationKey } from './i18n/t.ts';
// @ts-expect-error TS5097
import { createTranslator, type TranslateFn } from './i18n/translate.ts';

export type TrackedAnalysisStatus = {
  status: string;
  as_of: string;
  thesis_status?: string | null;
  /** Inputs pendientes del último modelo fundamental (los rellena el backend); null = sin información. */
  missing_inputs?: string[] | null;
};

// Claves técnicas del modelo → motivo en palabras (nunca el snake_case crudo).
const MISSING_INPUT_KEYS: Record<string, TranslationKey> = {
  revenue_history_two_periods: 'watchlist.analysisStatus.missingRevenueHistory',
  normalized_fcf_margin: 'watchlist.analysisStatus.missingFcfMargin',
  shares_diluted: 'watchlist.analysisStatus.missingShares',
  no_revenue_reported: 'watchlist.analysisStatus.missingNoRevenue',
  annual_revenue_missing: 'watchlist.analysisStatus.missingAnnualRevenue',
  fiscal_year: 'watchlist.analysisStatus.missingFiscalYear',
};

function missingReason(missing: string[] | null | undefined, t: TranslateFn): string | null {
  if (!missing || missing.length === 0) return null;
  const labels = [...new Set(missing.map((key) => t(Object.hasOwn(MISSING_INPUT_KEYS, key) ? MISSING_INPUT_KEYS[key] : 'watchlist.analysisStatus.missingAssumptions')))];
  if (labels.length === 1) return labels[0];
  if (labels.length === 2) return t('watchlist.analysisStatus.pair', { a: labels[0], b: labels[1] });
  return t('watchlist.analysisStatus.pairMore', { a: labels[0], b: labels[1], count: labels.length - 2 });
}

/** Estado del análisis de un ticker seguido, en el idioma elegido (español por defecto). */
export function analysisStatusLabel(analysis: TrackedAnalysisStatus | null | undefined, locale: Locale = DEFAULT_LOCALE): string | null {
  if (!analysis) return null;
  const t = createTranslator(locale);
  if (['queued', 'running', 'retrying'].includes(analysis.status)) return t('watchlist.analysisStatus.running');
  if (analysis.status === 'dispatch_failed') return t('watchlist.analysisStatus.retryPending');
  if (analysis.status === 'failed') return t('watchlist.analysisStatus.failed');
  if (analysis.status === 'succeeded') {
    if (analysis.thesis_status === 'insufficient_data') {
      const reason = missingReason(analysis.missing_inputs, t);
      return reason ? t('watchlist.analysisStatus.missingWithReason', { reason }) : t('watchlist.analysisStatus.missing');
    }
    return t('watchlist.analysisStatus.done');
  }
  return t('watchlist.analysisStatus.unavailable');
}
