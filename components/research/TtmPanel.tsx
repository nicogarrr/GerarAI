import { Badge } from '@/components/ui/badge';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { naFor } from '@/lib/format';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatResearchMetric } from '@/lib/research/metric-value';
import {
  type ResearchTtm,
  ttmHasData,
  ttmPanelMetrics,
  ttmPeriodText,
  ttmProvenanceLabel,
  ttmQuartersText,
} from '@/lib/research/ttm-display';

/**
 * Fundamentales actuales en TTM (últimos 4 trimestres) con respaldo FY.
 * Cada cifra dice su base (TTM / FY / último trimestre) y si es OFICIAL o
 * INFERIDO (Q4 = FY − 9 meses, o un trimestre sacado de acumulados).
 */
export function TtmPanel({ ttm, locale = DEFAULT_LOCALE }: { ttm: ResearchTtm | null; locale?: Locale }) {
  const t = createTranslator(locale);
  if (!ttmHasData(ttm)) {
    return (
      <p className="text-sm text-gray-400">{t('research.ttm.empty')}</p>
    );
  }
  const metrics = ttmPanelMetrics(ttm);
  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {metrics.map((metric) => {
          const quarters = ttmQuartersText(metric.quarters, locale);
          return (
            <div className="rounded-lg border border-gray-800 p-4" key={metric.metric}>
              <div className="flex items-center justify-between gap-3">
                <span className="min-w-0 break-words font-medium text-gray-200">{metricLabel(metric.metric, locale)}</span>
                <Badge className="shrink-0" variant="outline">{ttmProvenanceLabel(metric.provenance, locale)}</Badge>
              </div>
              <div className="mt-2 text-xl text-teal-300">
                {metric.value === null ? naFor(locale) : formatResearchMetric(metric.value, metric.unit ?? '')}
              </div>
              <div className="mt-2 text-xs text-gray-500">{ttmPeriodText(metric, locale)}</div>
              {quarters ? <div className="mt-1 text-xs leading-5 text-gray-500">{t('research.ttm.sumOf', { quarters })}</div> : null}
              {metric.note ? <div className="mt-1 text-xs leading-5 text-amber-300/80">{metric.note}</div> : null}
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs leading-5 text-gray-500">{ttm?.formula}</p>
    </div>
  );
}
