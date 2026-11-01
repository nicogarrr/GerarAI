import { Check, RefreshCcw, X } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { NA } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import { Textarea } from '@/components/ui/textarea';
import { decideDecisionLesson, getDecisionLessons, proposeDecisionLessons, updateDecisionLessonResult } from '@/lib/actions/research-tools.actions';

export type DecisionLessons = Awaited<ReturnType<typeof getDecisionLessons>>;

/** Estados persistidos por el backend -> clave de texto (es/en). */
const STATUS_KEYS = {
  proposed: 'research.lessonsSection.statusProposed',
  approved: 'research.lessonsSection.statusApproved',
  rejected: 'research.lessonsSection.statusRejected',
} as const;

function label(value: string | null | undefined, t: TranslateFn): string {
  if (!value) return '—';
  return Object.hasOwn(STATUS_KEYS, value) ? t(STATUS_KEYS[value as keyof typeof STATUS_KEYS]) : value.replaceAll('_', ' ');
}

/**
 * Lecciones de decisiones como sección de la pestaña Seguimiento (antes
 * página propia `/decision-lessons`, que ahora redirige aquí). Convierte
 * los desvíos de previsión en lecciones revisadas sin dejar que las
 * conclusiones generadas automáticamente se vuelvan canónicas en silencio.
 */
export function DecisionLessonsSection({ ticker, data, locale = 'es' }: { ticker: string; data: DecisionLessons; locale?: Locale }) {
  const t = createTranslator(locale);
  const { lessons, taxonomy } = data;
  return <div className="grid gap-6">
    <div className="flex flex-wrap gap-2"><MutationForm action={proposeDecisionLessons.bind(null, ticker)} successMessage={t('research.lessonsSection.proposed')}><Button type="submit" variant="outline"><RefreshCcw className="h-4 w-4" />{t('research.lessonsSection.proposeFromDeviations')}</Button></MutationForm></div>
    <section className="grid gap-5">{lessons.map((item) => <article className="rounded-xl border border-gray-800 bg-surface-1 p-5" key={item.id}><div className="flex flex-wrap items-center gap-2"><Badge className={item.status === 'approved' ? 'border-teal-800 text-teal-300' : item.status === 'rejected' ? 'border-red-900 text-red-300' : 'border-amber-900 text-amber-300'} variant="outline">{label(item.status, t)}</Badge><Badge variant="outline">{item.taxonomy}</Badge><span className="text-xs text-gray-500">{t('research.lessonsSection.meta', { id: item.id, decision: item.decision_journal_entry_id ?? t('research.lessonsSection.noLink'), review: item.expectation_review_id ?? NA })}</span></div><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><div className="rounded-lg border border-gray-800 p-3"><div className="text-xs font-semibold uppercase text-gray-500">{t('research.lessonsSection.expectation')}</div><p className="mt-2 text-sm text-gray-300">{item.expectation}</p></div><div className="rounded-lg border border-gray-800 p-3"><div className="text-xs font-semibold uppercase text-gray-500">{t('research.lessonsSection.outcome')}</div><p className="mt-2 text-sm text-gray-300">{item.outcome}</p></div><div className="rounded-lg border border-gray-800 p-3"><div className="text-xs font-semibold uppercase text-gray-500">{t('research.lessonsSection.deviation')}</div><p className="mt-2 text-sm text-gray-300">{item.deviation}</p></div></div>
      {item.status === 'approved' ? <div className="mt-4 grid gap-3 sm:grid-cols-2"><div className="rounded-lg border border-teal-900/40 bg-teal-950/10 p-4"><div className="text-xs font-semibold uppercase text-teal-400">{t('research.lessonsSection.approvedLesson')}</div><p className="mt-2 text-sm leading-6 text-gray-200">{item.lesson}</p></div><div className="rounded-lg border border-gray-800 p-4"><div className="text-xs font-semibold uppercase text-gray-500">{t('research.lessonsSection.futureApplication')}</div><p className="mt-2 text-sm leading-6 text-gray-300">{item.future_application}</p></div></div> : <MutationForm action={updateDecisionLessonResult.bind(null, ticker, item.id)} className="mt-4 grid gap-3" successMessage={t('research.lessonsSection.updated')}><select className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:h-9 sm:text-sm" defaultValue={item.taxonomy} name="taxonomy">{taxonomy.map((value) => <option key={value}>{value}</option>)}</select><div className="grid gap-3 sm:grid-cols-2"><Textarea defaultValue={item.cause} name="cause" placeholder={t('research.lessonsSection.rootCause')} required /><Textarea defaultValue={item.error} name="error" placeholder={t('research.lessonsSection.decisionError')} required /><Textarea defaultValue={item.lesson} name="lesson" placeholder={t('research.lessonsSection.lastingLesson')} required /><Textarea defaultValue={item.future_application} name="future_application" placeholder={t('research.lessonsSection.howItChanges')} required /></div><Button className="w-fit" type="submit">{t('research.lessonsSection.saveReview')}</Button></MutationForm>}
      {item.status === 'proposed' ? <div className="mt-4 flex gap-2"><MutationForm action={decideDecisionLesson.bind(null, ticker, item.id, 'approve')} successMessage={t('research.lessonsSection.approvedLesson')}><Button type="submit" size="sm"><Check className="h-4 w-4" />{t('research.lessonsSection.approve')}</Button></MutationForm><MutationForm action={decideDecisionLesson.bind(null, ticker, item.id, 'reject')} successMessage={t('research.lessonsSection.rejectedMsg')}><Button type="submit" size="sm" variant="outline"><X className="h-4 w-4" />{t('research.lessonsSection.reject')}</Button></MutationForm></div> : null}</article>)}{!lessons.length ? <EmptyState description={t('research.lessonsSection.emptyDescription')} title={t('research.lessonsSection.emptyTitle')} /> : null}</section>
  </div>;
}
