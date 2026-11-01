import { Database, SlidersHorizontal } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { OverflowScrollRegion } from '@/components/ui/overflow-scroll-region';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Stat } from '@/components/ui/stat';
import { getFinancialTerminal } from '@/lib/actions/research-tools.actions';
import { financialDefinition, financialFormula, financialPeriod, financialSegment, loadedFinancialRange } from '@/lib/research/financial-display';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatConfidence, NA } from '@/lib/format';
import { formatProvenanceValue } from '@/lib/research/provenance-format';

export type FinancialTerminalData = Awaited<ReturnType<typeof getFinancialTerminal>>;

/** Etiquetas en español para los estados persistidos por el backend */
const STATUS_LABELS: Record<string, string> = {
  reported: 'Publicado', normalized: 'Normalizado', calculated: 'Calculado', unknown: 'Sin identificar', annual: 'Anual', quarterly: 'Trimestral', all: 'Todos los periodos',
  available: 'disponible',
  partial: 'parcial',
  missing: 'faltante',
  unavailable: 'sin datos',
  blocked: 'bloqueada',
};

function label(value: string | null | undefined): string {
  if (!value) return '—';
  return STATUS_LABELS[value] ?? value.replaceAll('_', ' ');
}

function value(raw: string | number | null, unit: string) {
  if (raw === null || !Number.isFinite(Number(raw))) return NA;
  if (!unit?.trim()) return 'N/D (unidad no disponible)';
  return formatProvenanceValue(raw, unit);
}

/**
 * Terminal financiero como sección de la pestaña Finanzas (antes página
 * propia `/financial-terminal`, que ahora redirige aquí). El formulario de
 * controles es un GET a la propia ficha: el hidden `view=finanzas` mantiene
 * la pestaña al aplicar.
 */
export function FinancialTerminalSection({ terminal, metrics, years, periodicity }: { terminal: FinancialTerminalData; metrics?: string; years: number; periodicity: string }) {
  return <div className="grid min-w-0 gap-6">
    <section className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">{[['Cobertura', `${terminal.coverage.percent.toFixed(0)}%`], ['Disponibles', `${terminal.coverage.available}/${terminal.coverage.requested}`], ['Ejercicios cargados', loadedFinancialRange(terminal.metrics) ?? NA], ['Periodicidad', label(terminal.periodicity)]].map(([label, data]) => <Stat key={label} label={label} size="sm" value={data} />)}</section>
    <form className="rounded-xl border border-gray-800 bg-surface-1 p-4" method="get">
      <input type="hidden" name="view" value="finanzas" />
<div className="mb-3 flex items-center gap-2"><SlidersHorizontal aria-hidden="true" className="h-4 w-4 text-teal-300" /><h3 className="font-semibold text-gray-200">Controles del terminal</h3></div><div className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_120px_160px_auto]"><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Métricas</span><Input defaultValue={metrics} name="metrics" placeholder="Métricas, separadas por comas (vacío = por defecto)" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Años de historial (1-20)</span><Input defaultValue={years} max="20" min="1" name="years" type="number" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Periodicidad</span><select className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:h-9 sm:text-sm" defaultValue={periodicity} name="periodicity"><option value="annual">Anual</option><option value="quarterly">Trimestral</option><option value="all">Todos los periodos</option></select></label><Button type="submit">Aplicar</Button></div></form>
    <section className="grid min-w-0 gap-5">{terminal.metrics.map((metric) => <article className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5" key={metric.metric}>
<div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-start"><div className="min-w-0 [overflow-wrap:anywhere]"><div className="flex flex-wrap items-center gap-2"><h3 className="text-lg font-semibold text-gray-100">{metricLabel(metric.metric)}</h3><Badge className={metric.status === 'available' ? 'border-teal-800 text-teal-300' : 'border-amber-900 text-amber-300'} variant="outline">{label(metric.status)}</Badge></div><p className="mt-2 text-sm text-gray-400">{financialDefinition(metric.definition)}</p>{metric.canonical_formula ? <code className="mt-2 block text-xs text-teal-300">{financialFormula(metric.canonical_formula)}</code> : null}</div><div className="flex flex-wrap gap-2 md:ml-auto"><Badge variant="outline">{metric.periods} {metric.periods === 1 ? 'periodo' : 'periodos'}</Badge>{metric.segments.map((segment) => <Badge key={segment} variant="outline">{financialSegment(segment)}</Badge>)}</div></div>{metric.series.some((point) => point.period !== 'unknown' || point.value !== null) ? <OverflowScrollRegion label={`Serie de ${metricLabel(metric.metric)}`} className="mt-4 w-full min-w-0 max-w-full" regionClassName="overscroll-x-contain"><table className="w-full min-w-[640px] sm:min-w-[1000px] text-left text-sm"><caption className="sr-only">Serie de {metricLabel(metric.metric)} por periodo, con valor, estado, segmento, confianza y fuente</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2 pr-3" scope="col">Periodo</th><th className="border-b border-gray-800 px-3 py-2 text-right" scope="col">Valor</th><th className="border-b border-gray-800 px-3 py-2" scope="col">Estado</th><th className="border-b border-gray-800 px-3 py-2" scope="col">Segmento</th><th className="border-b border-gray-800 px-3 py-2 text-right" scope="col">Confianza</th><th className="border-b border-gray-800 py-2 pl-3" scope="col">Fuente</th></tr></thead><tbody>{metric.series.filter((point) => point.period !== 'unknown' || point.value !== null).map((point) => <tr className="border-b border-gray-900" key={`${point.id}-${point.period}-${point.status}`}><th className="py-3 pr-3 text-left text-sm font-medium text-gray-300" scope="row">{financialPeriod(point.period)}</th><td className="px-3 py-3 text-right font-semibold text-gray-100">{value(point.value, point.unit)}</td><td className="px-3 py-3"><Badge variant="outline">{label(point.status)}</Badge></td><td className="px-3 py-3 text-gray-400">{financialSegment(point.segment)}</td><td className="px-3 py-3 text-right text-gray-400">{formatConfidence(point.confidence)}</td><td className="py-3 pl-3 text-gray-500"><div className="flex items-center gap-1"><Database aria-hidden="true" className="h-3 w-3" />{point.source.title ?? point.source.type}</div></td></tr>)}</tbody></table></OverflowScrollRegion> : <EmptyState className="mt-4 p-4" description={metric.missing_reason ?? undefined} title={metric.missing_reason ? 'Sin datos para esta métrica.' : 'Sin observaciones para esta métrica y filtro de periodo.'} />}</article>)}</section>
  </div>;
}
