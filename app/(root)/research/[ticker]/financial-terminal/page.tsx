import Link from 'next/link';
import { ArrowLeft, Database, SlidersHorizontal } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { Stat } from '@/components/ui/stat';
import { getFinancialTerminal } from '@/lib/actions/research-tools.actions';
import { financialDefinition, financialFormula, financialPeriod, financialSegment } from '@/lib/research/financial-display';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatCompact, formatConfidence, formatPercent, NA } from '@/lib/format';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

/** Etiquetas en español para los estados persistidos por el backend */
const STATUS_LABELS: Record<string, string> = {
  reported: 'Publicado', normalized: 'Normalizado', calculated: 'Calculado', unknown: 'Sin identificar', annual: 'Anual', quarterly: 'Trimestral', all: 'Todos los periodos',
  available: 'disponible',
  partial: 'parcial',
  missing: 'faltante',
  blocked: 'bloqueada',
};

function label(value: string | null | undefined): string {
  if (!value) return '—';
  return STATUS_LABELS[value] ?? value.replaceAll('_', ' ');
}

function value(raw: string | number | null, unit: string) {
  if (raw === null) return NA;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return String(raw);
  if (unit === 'decimal') return formatPercent(parsed);
  return formatCompact(parsed);
}

export default async function FinancialTerminalPage({ params, searchParams }: { params: Promise<{ ticker: string }>; searchParams: Promise<{ metrics?: string; years?: string; periodicity?: string }> }) {
  const [{ ticker: rawTicker }, query] = await Promise.all([params, searchParams]);
  const ticker = rawTicker.toUpperCase();
  const years = Math.max(1, Math.min(20, Number(query.years) || 10));
  const periodicity = ['all', 'annual', 'quarterly'].includes(query.periodicity ?? '') ? query.periodicity! : 'annual';
  const terminal = await getFinancialTerminal(ticker, { metrics: query.metrics, years, periodicity });
  return <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-[1600px] flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <PageHeader back={<Button asChild size="sm" variant="ghost"><Link href={`/research/${ticker}`}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Ficha de {ticker}</Link></Button>} description="Métricas reportadas, normalizadas y calculadas con definiciones, fórmulas, confianza y trazabilidad de la fuente." kicker="Financieros con fuentes" title="Terminal financiero" />
    <section className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">{[['Cobertura', `${terminal.coverage.percent.toFixed(0)}%`], ['Disponibles', `${terminal.coverage.available}/${terminal.coverage.requested}`], ['Rango', `${terminal.range.from_fiscal_year}–${terminal.range.to_fiscal_year}`], ['Periodicidad', label(terminal.periodicity)]].map(([label, data]) => <Stat key={label} label={label} size="sm" value={data} />)}</section>
    <form className="rounded-xl border border-gray-800 bg-surface-1 p-4" method="get">
<div className="mb-3 flex items-center gap-2"><SlidersHorizontal aria-hidden="true" className="h-4 w-4 text-teal-300" /><h2 className="font-semibold text-gray-200">Controles del terminal</h2></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_120px_160px_auto]"><Input defaultValue={query.metrics} name="metrics" placeholder="Métricas, separadas por comas (vacío = por defecto)" /><Input defaultValue={years} max="20" min="1" name="years" type="number" /><select className="h-9 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200" defaultValue={periodicity} name="periodicity"><option value="annual">Anual</option><option value="quarterly">Trimestral</option><option value="all">Todos los periodos</option></select><Button type="submit">Aplicar</Button></div></form>
        <section className="grid min-w-0 gap-5">{terminal.metrics.map((metric) => <article className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5" key={metric.metric}>
<div className="flex flex-col gap-3 md:flex-row md:items-start"><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold text-gray-100">{metricLabel(metric.metric)}</h2><Badge className={metric.status === 'available' ? 'border-teal-800 text-teal-300' : 'border-amber-900 text-amber-300'} variant="outline">{label(metric.status)}</Badge></div><p className="mt-2 text-sm text-gray-400">{financialDefinition(metric.definition)}</p>{metric.canonical_formula ? <code className="mt-2 block text-xs text-teal-300">{financialFormula(metric.canonical_formula)}</code> : null}</div><div className="flex flex-wrap gap-2 md:ml-auto"><Badge variant="outline">{metric.periods} periodos</Badge>{metric.segments.map((segment) => <Badge key={segment} variant="outline">{financialSegment(segment)}</Badge>)}</div></div>{metric.series.length ? <div aria-label={`Serie de ${metricLabel(metric.metric)}`} className="mt-4 overflow-x-auto" role="region" tabIndex={0}><table className="w-full min-w-[640px] sm:min-w-[1000px] text-left text-sm"><caption className="sr-only">Serie de {metricLabel(metric.metric)} por periodo, con valor, estado, segmento, confianza y fuente</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2 pr-3" scope="col">Periodo</th><th className="border-b border-gray-800 px-3 py-2 text-right" scope="col">Valor</th><th className="border-b border-gray-800 px-3 py-2" scope="col">Estado</th><th className="border-b border-gray-800 px-3 py-2" scope="col">Segmento</th><th className="border-b border-gray-800 px-3 py-2 text-right" scope="col">Confianza</th><th className="border-b border-gray-800 py-2 pl-3" scope="col">Fuente</th></tr></thead><tbody>{metric.series.map((point) => <tr className="border-b border-gray-900" key={`${point.id}-${point.period}-${point.status}`}><th className="py-3 pr-3 text-left text-sm font-medium text-gray-300" scope="row">{financialPeriod(point.period)}</th><td className="px-3 py-3 text-right font-semibold text-gray-100">{value(point.value, point.unit)} <span className="text-xs font-normal text-gray-500">{point.unit}</span></td><td className="px-3 py-3"><Badge variant="outline">{label(point.status)}</Badge></td><td className="px-3 py-3 text-gray-400">{financialSegment(point.segment)}</td><td className="px-3 py-3 text-right text-gray-400">{formatConfidence(point.confidence)}</td><td className="py-3 pl-3 text-gray-500"><div className="flex items-center gap-1"><Database aria-hidden="true" className="h-3 w-3" />{point.source.title ?? point.source.type}</div></td></tr>)}</tbody></table></div> : <EmptyState className="mt-4 p-4" title="Sin observaciones para esta métrica y filtro de periodo." />}</article>)}</section>
  </main>;
}
