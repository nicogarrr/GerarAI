import { Check, RefreshCcw, X } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { NA } from '@/lib/format';
import { Textarea } from '@/components/ui/textarea';
import { decideDecisionLesson, getDecisionLessons, proposeDecisionLessons, updateDecisionLesson } from '@/lib/actions/research-tools.actions';

export type DecisionLessons = Awaited<ReturnType<typeof getDecisionLessons>>;

/** Etiquetas en español para los estados persistidos por el backend */
const STATUS_LABELS: Record<string, string> = {
  proposed: 'propuesta',
  approved: 'aprobada',
  rejected: 'rechazada',
};

function label(value: string | null | undefined): string {
  if (!value) return '—';
  return STATUS_LABELS[value] ?? value.replaceAll('_', ' ');
}

/**
 * Lecciones de decisiones como sección de la pestaña Seguimiento (antes
 * página propia `/decision-lessons`, que ahora redirige aquí). Convierte
 * los desvíos de previsión en lecciones revisadas sin dejar que las
 * conclusiones generadas automáticamente se vuelvan canónicas en silencio.
 */
export function DecisionLessonsSection({ ticker, data }: { ticker: string; data: DecisionLessons }) {
  const { lessons, taxonomy } = data;
  return <div className="grid gap-6">
    <div className="flex flex-wrap gap-2"><MutationForm action={proposeDecisionLessons.bind(null, ticker)} successMessage="Lecciones propuestas"><Button type="submit" variant="outline"><RefreshCcw className="h-4 w-4" />Proponer desde desvíos</Button></MutationForm></div>
    <section className="grid gap-5">{lessons.map((item) => <article className="rounded-xl border border-gray-800 bg-surface-1 p-5" key={item.id}><div className="flex flex-wrap items-center gap-2"><Badge className={item.status === 'approved' ? 'border-teal-800 text-teal-300' : item.status === 'rejected' ? 'border-red-900 text-red-300' : 'border-amber-900 text-amber-300'} variant="outline">{label(item.status)}</Badge><Badge variant="outline">{item.taxonomy}</Badge><span className="text-xs text-gray-500">Lección #{item.id} · decisión #{item.decision_journal_entry_id ?? 'sin vínculo'} · revisión #{item.expectation_review_id ?? NA}</span></div><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><div className="rounded-lg border border-gray-800 p-3"><div className="text-xs font-semibold uppercase text-gray-500">Expectativa</div><p className="mt-2 text-sm text-gray-300">{item.expectation}</p></div><div className="rounded-lg border border-gray-800 p-3"><div className="text-xs font-semibold uppercase text-gray-500">Resultado</div><p className="mt-2 text-sm text-gray-300">{item.outcome}</p></div><div className="rounded-lg border border-gray-800 p-3"><div className="text-xs font-semibold uppercase text-gray-500">Desviación</div><p className="mt-2 text-sm text-gray-300">{item.deviation}</p></div></div>
      {item.status === 'approved' ? <div className="mt-4 grid gap-3 sm:grid-cols-2"><div className="rounded-lg border border-teal-900/40 bg-teal-950/10 p-4"><div className="text-xs font-semibold uppercase text-teal-400">Lección aprobada</div><p className="mt-2 text-sm leading-6 text-gray-200">{item.lesson}</p></div><div className="rounded-lg border border-gray-800 p-4"><div className="text-xs font-semibold uppercase text-gray-500">Aplicación futura</div><p className="mt-2 text-sm leading-6 text-gray-300">{item.future_application}</p></div></div> : <MutationForm action={updateDecisionLesson.bind(null, ticker, item.id)} className="mt-4 grid gap-3" successMessage="Lección actualizada"><select className="h-9 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200" defaultValue={item.taxonomy} name="taxonomy">{taxonomy.map((value) => <option key={value}>{value}</option>)}</select><div className="grid gap-3 sm:grid-cols-2"><Textarea defaultValue={item.cause} name="cause" placeholder="Causa raíz" required /><Textarea defaultValue={item.error} name="error" placeholder="Error de decisión" required /><Textarea defaultValue={item.lesson} name="lesson" placeholder="Lección duradera" required /><Textarea defaultValue={item.future_application} name="future_application" placeholder="Cómo cambia las decisiones futuras" required /></div><Button className="w-fit" type="submit">Guardar revisión del analista</Button></MutationForm>}
      {item.status === 'proposed' ? <div className="mt-4 flex gap-2"><MutationForm action={decideDecisionLesson.bind(null, ticker, item.id, 'approve')} successMessage="Lección aprobada"><Button type="submit" size="sm"><Check className="h-4 w-4" />Aprobar</Button></MutationForm><MutationForm action={decideDecisionLesson.bind(null, ticker, item.id, 'reject')} successMessage="Lección rechazada"><Button type="submit" size="sm" variant="outline"><X className="h-4 w-4" />Rechazar</Button></MutationForm></div> : null}</article>)}{!lessons.length ? <EmptyState description="Revisa los resultados de las previsiones y propón lecciones desde los desvíos." title="Aún no hay lecciones de decisiones." /> : null}</section>
  </div>;
}
