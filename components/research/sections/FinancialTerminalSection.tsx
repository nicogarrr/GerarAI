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
import { formatConfidence, naFor } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import type { TranslationKey } from '@/lib/i18n/t';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import { formatProvenanceValue } from '@/lib/research/provenance-format';

export type FinancialTerminalData = Awaited<ReturnType<typeof getFinancialTerminal>>;

/** Estados persistidos por el backend con etiqueta traducida (research.terminalSection.status). */
const STATUS_KEYS: Record<string, TranslationKey> = { reported: 'research.terminalSection.status.reported', normalized: 'research.terminalSection.status.normalized', calculated: 'research.terminalSection.status.calculated', unknown: 'research.terminalSection.status.unknown', annual: 'research.terminalSection.status.annual', quarterly: 'research.terminalSection.status.quarterly', all: 'research.terminalSection.status.all', available: 'research.terminalSection.status.available', partial: 'research.terminalSection.status.partial', missing: 'research.terminalSection.status.missing', unavailable: 'research.terminalSection.status.unavailable', blocked: 'research.terminalSection.status.blocked' };

function label(value: string | null | undefined, t: TranslateFn): string {
  if (!value) return '—';
  return STATUS_KEYS[value] ? t(STATUS_KEYS[value]) : value.replaceAll('_', ' ');
}

function value(raw: string | number | null, unit: string, t: TranslateFn, locale: Locale) {
  if (raw === null || !Number.isFinite(Number(raw))) return naFor(locale);
  if (!unit?.trim()) return t('research.terminalSection.noUnit');
  return formatProvenanceValue(raw, unit, locale);
}

/**
 * Terminal financiero como sección de la pestaña Finanzas (antes página
 * propia `/financial-terminal`, que ahora redirige aquí). El formulario de
 * controles es un GET a la propia ficha: el hidden `view=finanzas` mantiene
 * la pestaña al aplicar.
 */
export function FinancialTerminalSection({ terminal, metrics, years, periodicity, locale = DEFAULT_LOCALE }: { terminal: FinancialTerminalData; metrics?: string; years: number; periodicity: string; locale?: Locale }) {
  const t = createTranslator(locale);
  return <div className="grid min-w-0 gap-6">
    <section className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">{[[t('research.terminalSection.coverage'), `${terminal.coverage.percent.toFixed(0)}%`], [t('research.terminalSection.available'), `${terminal.coverage.available}/${terminal.coverage.requested}`], [t('research.terminalSection.yearsLoaded'), loadedFinancialRange(terminal.metrics) ?? naFor(locale)], [t('research.terminalSection.periodicity'), label(terminal.periodicity, t)]].map(([label, data]) => <Stat key={label} label={label} size="sm" value={data} />)}</section>
    <form className="rounded-xl border border-gray-800 bg-surface-1 p-4" method="get">
      <input type="hidden" name="view" value="finanzas" />
<div className="mb-3 flex items-center gap-2"><SlidersHorizontal aria-hidden="true" className="h-4 w-4 text-teal-300" /><h3 className="font-semibold text-gray-200">{t('research.terminalSection.controls')}</h3></div><div className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_120px_160px_auto]"><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.terminalSection.metrics')}</span><Input defaultValue={metrics} name="metrics" placeholder={t('research.terminalSection.metricsPlaceholder')} /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.terminalSection.yearsLabel')}</span><Input defaultValue={years} max="20" min="1" name="years" type="number" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.terminalSection.periodicity')}</span><select className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:h-9 sm:text-sm" defaultValue={periodicity} name="periodicity"><option value="annual">{t(STATUS_KEYS.annual)}</option><option value="quarterly">{t(STATUS_KEYS.quarterly)}</option><option value="all">{t(STATUS_KEYS.all)}</option></select></label><Button type="submit">{t('research.terminalSection.apply')}</Button></div></form>
    <section className="grid min-w-0 gap-5">{terminal.metrics.map((metric) => <article className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5" key={metric.metric}>
<div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-start"><div className="min-w-0 [overflow-wrap:anywhere]"><div className="flex flex-wrap items-center gap-2"><h3 className="text-lg font-semibold text-gray-100">{metricLabel(metric.metric, locale)}</h3><Badge className={metric.status === 'available' ? 'border-teal-800 text-teal-300' : 'border-amber-900 text-amber-300'} variant="outline">{label(metric.status, t)}</Badge></div><p className="mt-2 text-sm text-gray-400">{financialDefinition(metric.definition, locale)}</p>{metric.canonical_formula ? <code className="mt-2 block text-xs text-teal-300">{financialFormula(metric.canonical_formula, locale)}</code> : null}</div><div className="flex flex-wrap gap-2 md:ml-auto"><Badge variant="outline">{t(metric.periods === 1 ? 'research.terminalSection.periodOne' : 'research.terminalSection.periodMany', { count: metric.periods })}</Badge>{metric.segments.map((segment) => <Badge key={segment} variant="outline">{financialSegment(segment, locale)}</Badge>)}</div></div>{metric.series.some((point) => point.period !== 'unknown' || point.value !== null) ? <OverflowScrollRegion label={t('research.terminalSection.seriesLabel', { metric: metricLabel(metric.metric, locale) })} className="mt-4 w-full min-w-0 max-w-full" regionClassName="overscroll-x-contain"><table className="w-full min-w-[640px] sm:min-w-[1000px] text-left text-sm"><caption className="sr-only">{t('research.terminalSection.seriesCaption', { metric: metricLabel(metric.metric, locale) })}</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2 pr-3" scope="col">{t('research.terminalSection.colPeriod')}</th><th className="border-b border-gray-800 px-3 py-2 text-right" scope="col">{t('research.terminalSection.colValue')}</th><th className="border-b border-gray-800 px-3 py-2" scope="col">{t('research.terminalSection.colStatus')}</th><th className="border-b border-gray-800 px-3 py-2" scope="col">{t('research.terminalSection.colSegment')}</th><th className="border-b border-gray-800 px-3 py-2 text-right" scope="col">{t('research.terminalSection.colConfidence')}</th><th className="border-b border-gray-800 py-2 pl-3" scope="col">{t('research.terminalSection.colSource')}</th></tr></thead><tbody>{metric.series.filter((point) => point.period !== 'unknown' || point.value !== null).map((point) => <tr className="border-b border-gray-900" key={`${point.id}-${point.period}-${point.status}`}><th className="py-3 pr-3 text-left text-sm font-medium text-gray-300" scope="row">{financialPeriod(point.period, locale)}</th><td className="px-3 py-3 text-right font-semibold text-gray-100">{value(point.value, point.unit, t, locale)}</td><td className="px-3 py-3"><Badge variant="outline">{label(point.status, t)}</Badge></td><td className="px-3 py-3 text-gray-400">{financialSegment(point.segment, locale)}</td><td className="px-3 py-3 text-right text-gray-400">{formatConfidence(point.confidence)}</td><td className="py-3 pl-3 text-gray-500"><div className="flex items-center gap-1"><Database aria-hidden="true" className="h-3 w-3" />{point.source.title ?? point.source.type}</div></td></tr>)}</tbody></table></OverflowScrollRegion> : <EmptyState className="mt-4 p-4" description={metric.missing_reason ?? undefined} title={metric.missing_reason ? t('research.terminalSection.noData') : t('research.terminalSection.noObservations')} />}</article>)}</section>
  </div>;
}
