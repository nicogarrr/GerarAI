import { RefreshCcw, UploadCloud } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { formatPercent, formatUserDate, NA } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import { Input } from '@/components/ui/input';
import { Stat } from '@/components/ui/stat';
import { Textarea } from '@/components/ui/textarea';
import { createManagementPromiseResult, getManagementCredibility, importManagementCallClaims, reconcileManagementCredibility, updateManagementExplanationResult } from '@/lib/actions/research-tools.actions';

export type ManagementCredibility = Awaited<ReturnType<typeof getManagementCredibility>>;

/** Estados, calificación y método del backend -> clave de texto (es/en). */
const STATUS_KEYS = {
  open: 'research.managementSection.statusOpen',
  met: 'research.managementSection.statusMet',
  partial: 'research.managementSection.statusPartial',
  missed: 'research.managementSection.statusMissed',
} as const;

const GRADE_KEYS = {
  high: 'research.managementSection.gradeHigh',
  mixed: 'research.managementSection.gradeMixed',
  low: 'research.managementSection.gradeLow',
  insufficient_history: 'research.managementSection.gradeInsufficient',
} as const;
const METHOD_KEYS = {
  'resolved promises: met=1, partial=0.5, missed=0': 'research.managementSection.methodResolved',
} as const;

function pick<T extends Record<string, string>>(table: T, value: string): T[keyof T] | null {
  return Object.hasOwn(table, value) ? table[value as keyof T] : null;
}

function label(value: string | null | undefined, t: TranslateFn): string {
  if (!value) return '—';
  const key = pick(STATUS_KEYS, value);
  return key ? t(key) : value.replaceAll('_', ' ');
}

/**
 * Credibilidad de la directiva como sección de la pestaña Seguimiento
 * (antes página propia `/management-credibility`, que ahora redirige aquí).
 * Registra promesas fechadas y las reconcilia con los hechos financieros
 * canónicos, con las mismas acciones que la página histórica.
 */
export function ManagementCredibilitySection({ ticker, dashboard, locale = 'es' }: { ticker: string; dashboard: ManagementCredibility; locale?: Locale }) {
  const t = createTranslator(locale);
  const grade = pick(GRADE_KEYS, dashboard.grade);
  const method = pick(METHOD_KEYS, dashboard.method);
  return <div className="grid gap-6">
    <div className="flex flex-wrap gap-2"><MutationForm action={importManagementCallClaims.bind(null, ticker)} successMessage={t('research.managementSection.claimsImported')}><Button className="h-auto whitespace-normal py-2 text-center" type="submit" variant="outline"><UploadCloud className="h-4 w-4" />{t('research.managementSection.importClaims')}</Button></MutationForm><MutationForm action={reconcileManagementCredibility.bind(null, ticker)} successMessage={t('research.managementSection.reconciled')}><Button type="submit"><RefreshCcw className="h-4 w-4" />{t('research.managementSection.reconcile')}</Button></MutationForm></div>
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-6">{[[t('research.managementSection.score'), formatPercent(dashboard.score, { digits: 0 }, undefined, locale)], [t('research.managementSection.grade'), grade ? t(grade) : dashboard.grade], [t('research.managementSection.open'), dashboard.counts.open], [t('research.managementSection.met'), dashboard.counts.met], [t('research.managementSection.partial'), dashboard.counts.partial], [t('research.managementSection.missed'), dashboard.counts.missed]].map(([label, value]) => <Stat key={String(label)} label={String(label)} size="sm" value={value} />)}</section>
    <MutationForm action={createManagementPromiseResult.bind(null, ticker)} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage={t('research.managementSection.recorded')}>
<h3 className="font-semibold text-gray-100">{t('research.managementSection.recordTitle')}</h3><div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 md:col-span-3"><span>{t('research.managementSection.promise')}</span><Textarea name="promise" placeholder={t('research.managementSection.promisePh')} required /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.managementSection.promiseDate')}</span><Input name="promise_date" required type="date" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.managementSection.expectedPeriod')}</span><Input name="expected_period" placeholder={t('research.managementSection.expectedPeriodPh')} required /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.managementSection.metricOptional')}</span><Input name="metric" placeholder={t('research.managementSection.metricOptional')} /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.managementSection.comparison')}</span><select className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:h-9 sm:text-sm" defaultValue="" name="operator"><option value="">{t('research.managementSection.qualitativeOption')}</option>{['>', '>=', '<', '<=', '=='].map((item) => <option key={item}>{item}</option>)}</select></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.managementSection.targetOptional')}</span><Input name="target_value" placeholder={t('research.managementSection.target')} type="text" inputMode="decimal" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.managementSection.unitOptional')}</span><Input name="unit" placeholder={t('research.managementSection.unit')} /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.managementSection.sourceDocOptional')}</span><Input name="source_document_id" placeholder={t('research.managementSection.sourceDoc')} type="number" min="1" /></label><Button className="w-fit" type="submit">{t('research.managementSection.recordButton')}</Button></div></MutationForm>
    <section className="grid gap-4">{dashboard.promises.map((promise) => <article className="rounded-xl border border-gray-800 bg-surface-1 p-5" key={promise.id}>
<div className="flex flex-col gap-3 md:flex-row md:items-start"><div><div className="flex flex-wrap items-center gap-2"><Badge className={promise.status === 'met' ? 'border-teal-800 text-teal-300' : promise.status === 'missed' ? 'border-red-900 text-red-300' : promise.status === 'partial' ? 'border-amber-900 text-amber-300' : ''} variant="outline">{label(promise.status, t)}</Badge><span className="text-xs text-gray-500">{t('research.managementSection.promisedExpected', { date: formatUserDate(promise.promise_date, undefined, undefined, locale), period: promise.expected_period })}</span></div><h3 className="mt-3 font-semibold leading-6 text-gray-100">{promise.promise}</h3></div><div className="rounded-lg border border-gray-800 p-3 text-sm md:ml-auto md:min-w-56"><div className="text-xs uppercase text-gray-500">{t('research.managementSection.targetActual')}</div><div className="mt-2 text-gray-200">{promise.metric ?? t('research.managementSection.qualitative')} {promise.operator ?? ''} {promise.target_value ?? NA} {promise.unit ?? ''}</div><div className="mt-1 text-teal-300">{t('research.managementSection.actual', { value: promise.actual_value ?? t('research.managementSection.pending') })}</div></div></div><MutationForm action={updateManagementExplanationResult.bind(null, ticker, promise.id)} className="mt-4 flex flex-col gap-2 md:flex-row md:items-end" successMessage={t('research.managementSection.explanationSaved')}><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 flex-1"><span>{t('research.managementSection.explanation')}</span><Input defaultValue={promise.management_explanation ?? ''} name="explanation" placeholder={t('research.managementSection.explanation')} required /></label><Button type="submit" variant="outline">{t('research.managementSection.saveExplanation')}</Button></MutationForm></article>)}{!dashboard.promises.length ? <EmptyState title={t('research.managementSection.empty')} /> : null}</section>
    <p className="text-xs text-gray-500">{t('research.managementSection.methodNote', { method: method ? t(method) : dashboard.method })}</p>
  </div>;
}
