import { Badge } from '@/components/ui/badge';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatResearchMetric } from '@/lib/research/metric-value';
import {
  type ResearchTtm,
  ttmHasData,
  ttmPanelMetrics,
  ttmPeriodText,
  ttmQuartersText,
} from '@/lib/research/ttm-display';

/**
 * Fundamentales actuales en TTM (últimos 4 trimestres) con respaldo FY.
 * Cada cifra dice su base (TTM / FY / último trimestre) y si es OFICIAL o
 * INFERIDO (Q4 = FY − 9 meses, o un trimestre sacado de acumulados).
 */
export function TtmPanel({ ttm }: { ttm: ResearchTtm | null }) {
  if (!ttmHasData(ttm)) {
    return (
      <p className="text-sm text-gray-400">
        Sin trimestres ni ejercicios guardados para calcular el TTM. Refresca los financieros (SEC) para traer los 10-Q.
      </p>
    );
  }
  const metrics = ttmPanelMetrics(ttm);
  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {metrics.map((metric) => {
          const quarters = ttmQuartersText(metric.quarters);
          return (
            <div className="rounded-lg border border-gray-800 p-4" key={metric.metric}>
              <div className="flex items-center justify-between gap-3">
                <span className="min-w-0 break-words font-medium text-gray-200">{metricLabel(metric.metric)}</span>
                <Badge className="shrink-0" variant="outline">{metric.provenance === 'SIN_DATOS' ? 'Sin datos' : metric.provenance}</Badge>
              </div>
              <div className="mt-2 text-xl text-teal-300">
                {metric.value === null ? 'N/D' : formatResearchMetric(metric.value, metric.unit ?? '')}
              </div>
              <div className="mt-2 text-xs text-gray-500">{ttmPeriodText(metric)}</div>
              {quarters ? <div className="mt-1 text-xs leading-5 text-gray-500">Suma de: {quarters}</div> : null}
              {metric.note ? <div className="mt-1 text-xs leading-5 text-amber-300/80">{metric.note}</div> : null}
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs leading-5 text-gray-500">{ttm?.formula}</p>
    </div>
  );
}
