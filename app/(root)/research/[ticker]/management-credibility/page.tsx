import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft, RefreshCcw, UploadCloud } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { formatPercent, formatUserDate, NA } from '@/lib/format';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { Stat } from '@/components/ui/stat';
import { Textarea } from '@/components/ui/textarea';
import { createManagementPromise, getManagementCredibility, importManagementCallClaims, reconcileManagementCredibility, updateManagementExplanation } from '@/lib/actions/research-tools.actions';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
  title: 'Credibilidad de la directiva',
  description: 'Promesas fechadas de la directiva reconciliadas con los hechos financieros.',
};

/** Etiquetas en español para los estados persistidos por el backend */
const STATUS_LABELS: Record<string, string> = {
  open: 'abierta',
  met: 'cumplida',
  partial: 'Parcial',
  missed: 'fallida',
};

const GRADE_LABELS: Record<string, string> = {
  high: 'alta',
  mixed: 'mixta',
  low: 'baja',
  insufficient_history: 'historial insuficiente',
};
const METHOD_ES: Record<string, string> = {
  'resolved promises: met=1, partial=0.5, missed=0': 'promesas resueltas: cumplida = 1, parcial = 0,5, fallida = 0',
};

function label(value: string | null | undefined): string {
  if (!value) return '—';
  return STATUS_LABELS[value] ?? value.replaceAll('_', ' ');
}

export default async function ManagementCredibilityPage({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  const dashboard = await getManagementCredibility(ticker);
    return <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-7xl flex-col gap-6"><PageHeader actions={<div className="flex flex-wrap gap-2"><MutationForm action={importManagementCallClaims.bind(null, ticker)} successMessage="Afirmaciones de la llamada importadas"><Button className="h-auto whitespace-normal py-2 text-center" type="submit" variant="outline"><UploadCloud className="h-4 w-4" />Importar afirmaciones de la llamada</Button></MutationForm><MutationForm action={reconcileManagementCredibility.bind(null, ticker)} successMessage="Promesas reconciliadas"><Button type="submit"><RefreshCcw className="h-4 w-4" />Reconciliar</Button></MutationForm></div>} back={<Button asChild className="min-h-[44px] sm:min-h-0" size="sm" variant="ghost"><Link href={`/research/${ticker}`}><ArrowLeft className="h-4 w-4" />Workspace de {ticker}</Link></Button>} description="Registra promesas fechadas y recóncilialas con los hechos financieros canónicos." kicker="Responsabilidad de la directiva" title="Credibilidad de la directiva" />
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-6">{[['Puntuación', formatPercent(dashboard.score, { digits: 0 })], ['Calificación', GRADE_LABELS[dashboard.grade] ?? dashboard.grade], ['Abiertas', dashboard.counts.open], ['Cumplidas', dashboard.counts.met], ['Parciales', dashboard.counts.partial], ['Fallidas', dashboard.counts.missed]].map(([label, value]) => <Stat key={String(label)} label={String(label)} size="sm" value={value} />)}</section>
    <MutationForm action={createManagementPromise.bind(null, ticker)} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Promesa registrada">
<h2 className="font-semibold text-gray-100">Registrar una promesa</h2><div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 md:col-span-3"><span>Promesa de la directiva</span><Textarea name="promise" placeholder="Promesa o guidance exacta de la directiva" required /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Fecha de la promesa</span><Input name="promise_date" required type="date" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Periodo esperado</span><Input name="expected_period" placeholder="FY2027 o Q4 2026" required /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Métrica canónica (opcional)</span><Input name="metric" placeholder="Métrica canónica (opcional)" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Comparación con el objetivo</span><select className="h-9 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200" defaultValue="" name="operator"><option value="">Cualitativa / sin objetivo</option>{['>', '>=', '<', '<=', '=='].map((item) => <option key={item}>{item}</option>)}</select></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Valor objetivo (opcional)</span><Input name="target_value" placeholder="Valor objetivo" type="text" inputMode="decimal" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Unidad (opcional)</span><Input name="unit" placeholder="Unidad" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>ID del documento fuente (opcional)</span><Input name="source_document_id" placeholder="ID del documento fuente" type="number" min="1" /></label><Button className="w-fit" type="submit">Registrar promesa</Button></div></MutationForm>
        <section className="grid gap-4">{dashboard.promises.map((promise) => <article className="rounded-xl border border-gray-800 bg-surface-1 p-5" key={promise.id}>
<div className="flex flex-col gap-3 md:flex-row md:items-start"><div><div className="flex flex-wrap items-center gap-2"><Badge className={promise.status === 'met' ? 'border-teal-800 text-teal-300' : promise.status === 'missed' ? 'border-red-900 text-red-300' : promise.status === 'partial' ? 'border-amber-900 text-amber-300' : ''} variant="outline">{label(promise.status)}</Badge><span className="text-xs text-gray-500">prometida {formatUserDate(promise.promise_date)} · esperada {promise.expected_period}</span></div><h2 className="mt-3 font-semibold leading-6 text-gray-100">{promise.promise}</h2></div><div className="rounded-lg border border-gray-800 p-3 text-sm md:ml-auto md:min-w-56"><div className="text-xs uppercase text-gray-500">Objetivo / real</div><div className="mt-2 text-gray-200">{promise.metric ?? 'cualitativa'} {promise.operator ?? ''} {promise.target_value ?? NA} {promise.unit ?? ''}</div><div className="mt-1 text-teal-300">real {promise.actual_value ?? 'pendiente'}</div></div></div><MutationForm action={updateManagementExplanation.bind(null, ticker, promise.id)} className="mt-4 flex flex-col gap-2 md:flex-row md:items-end" successMessage="Explicación guardada"><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 flex-1"><span>Explicación de la directiva o contexto del analista</span><Input defaultValue={promise.management_explanation ?? ''} name="explanation" placeholder="Explicación de la directiva o contexto del analista" required /></label><Button type="submit" variant="outline">Guardar explicación</Button></MutationForm></article>)}{!dashboard.promises.length ? <EmptyState title="Aún no hay promesas registradas." /> : null}</section>
<p className="text-xs text-gray-500">Método: {METHOD_ES[dashboard.method] ?? dashboard.method}. Los resultados dependen del mapeo de métricas canónicas y de los hechos reportados disponibles.</p>
  </main>;
}
