import Link from 'next/link';
import { ArrowLeft, RefreshCcw, UploadCloud } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { formatPercent, NA } from '@/lib/format';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { Stat } from '@/components/ui/stat';
import { Textarea } from '@/components/ui/textarea';
import { createManagementPromise, extractManagementCandidates, getManagementCredibility, importManagementCallClaims, reconcileManagementCredibility, updateManagementExplanation } from '@/lib/actions/research-tools.actions';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

/** Etiquetas en español para los estados persistidos por el backend */
const STATUS_LABELS: Record<string, string> = {
  open: 'abierta',
  met: 'cumplida',
  partial: 'Parcial',
  missed: 'fallida',
  candidate: 'sugerido, sin verificar',
  outcome_recorded: 'resultado registrado, sin veredicto',
};

const FLAG_LABELS: Record<string, string> = {
  conditional: 'condicional',
  negation_present: 'contiene negación',
};

const DATE_BASIS_LABELS: Record<string, string> = {
  call_date: 'fecha de la llamada (indicada al registrar)',
  user_entered: 'fecha introducida por quien registra, no verificada',
  registered_at: 'fecha de alta en el sistema, NO la de la llamada',
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
    return <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6"><PageHeader actions={<div className="flex flex-wrap gap-2"><MutationForm action={importManagementCallClaims.bind(null, ticker)} successMessage="Afirmaciones de la llamada importadas"><Button className="h-auto whitespace-normal py-2 text-center" type="submit" variant="outline"><UploadCloud className="h-4 w-4" />Importar afirmaciones de la llamada</Button></MutationForm><MutationForm action={reconcileManagementCredibility.bind(null, ticker)} successMessage="Promesas reconciliadas"><Button type="submit"><RefreshCcw className="h-4 w-4" />Reconciliar</Button></MutationForm></div>} back={<Button asChild className="min-h-[44px] sm:min-h-0" size="sm" variant="ghost"><Link href={`/research/${ticker}`}><ArrowLeft className="h-4 w-4" />Workspace de {ticker}</Link></Button>} description="Registra promesas fechadas y recóncilialas con los hechos financieros canónicos." kicker="Responsabilidad de la directiva" title="Credibilidad de la directiva" />
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-7">{[['Puntuación', formatPercent(dashboard.score, { digits: 0 })], ['Calificación', GRADE_LABELS[dashboard.grade] ?? dashboard.grade], ['Abiertas', dashboard.counts.open], ['Sugeridos', dashboard.counts.candidate ?? 0], ['Cumplidas', dashboard.counts.met], ['Parciales', dashboard.counts.partial], ['Fallidas', dashboard.counts.missed]].map(([label, value]) => <Stat key={String(label)} label={String(label)} size="sm" value={value} />)}</section>
    <MutationForm action={extractManagementCandidates.bind(null, ticker)} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Candidatos extraídos (sin verificar)">
<h2 className="font-semibold text-gray-100">Extraer candidatos de una transcripción</h2><p className="mt-1 text-xs text-gray-500">Reglas deterministas, sin IA. Solo propone frases de la directiva con verbo de futuro y dato comprobable; no se guarda la transcripción, solo la cita corta. Un candidato no es una promesa confirmada ni se marca cumplido o fallido sin evidencia.</p><div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2"><Textarea className="sm:col-span-2" name="transcript_text" placeholder="Texto de la transcripción oficial" required /><Input name="call_date" required type="date" /><Input name="source_url" placeholder="URL oficial de la transcripción (https://…)" required type="url" /><Button className="w-fit" type="submit">Extraer candidatos</Button></div></MutationForm>
    <MutationForm action={createManagementPromise.bind(null, ticker)} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Promesa registrada">
<h2 className="font-semibold text-gray-100">Registrar una promesa</h2><div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"><Textarea className="md:col-span-3" name="promise" placeholder="Promesa o guidance exacta de la directiva" required /><Input name="promise_date" required type="date" /><Input name="expected_period" placeholder="FY2027 o Q4 2026" required /><Input name="metric" placeholder="Métrica canónica (opcional)" /><select className="h-9 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200" defaultValue="" name="operator"><option value="">Cualitativa / sin objetivo</option>{['>', '>=', '<', '<=', '=='].map((item) => <option key={item}>{item}</option>)}</select><Input name="target_value" placeholder="Valor objetivo" step="any" type="number" /><Input name="unit" placeholder="Unidad" /><Input name="source_document_id" placeholder="ID del documento fuente" type="number" min="1" /><Button className="w-fit" type="submit">Registrar promesa</Button></div></MutationForm>
        <section className="grid gap-4">{dashboard.promises.map((promise) => <article className="rounded-xl border border-gray-800 bg-surface-1 p-5" key={promise.id}>
<div className="flex flex-col gap-3 md:flex-row md:items-start"><div><div className="flex flex-wrap items-center gap-2"><Badge className={promise.status === 'met' ? 'border-teal-800 text-teal-300' : promise.status === 'missed' ? 'border-red-900 text-red-300' : promise.status === 'partial' ? 'border-amber-900 text-amber-300' : ''} variant="outline">{label(promise.status)}</Badge>{promise.legacy_heuristic_target ? <Badge className="border-amber-900 text-amber-300" variant="outline">objetivo deducido, no fiable</Badge> : null}<span className="text-xs text-gray-500">prometida {promise.promise_date} · esperada {promise.expected_period}</span></div><h2 className="mt-3 font-semibold leading-6 text-gray-100">{promise.quote_literal ? `“${promise.quote_literal}”` : promise.promise}</h2>{promise.quote_literal || promise.speaker || promise.source_url ? <dl className="mt-3 grid gap-1 text-xs text-gray-400"><div>{promise.speaker ?? 'hablante no registrado'}{promise.speaker_role ? `, ${promise.speaker_role}` : ''}</div>{promise.call_date ? <div>Llamada: {promise.call_date} ({DATE_BASIS_LABELS[promise.date_basis ?? ''] ?? 'base de fecha no registrada'})</div> : <div>Fecha de la llamada: no registrada</div>}{promise.due_date ? <div>Vencimiento orientativo: {promise.due_date} (derivado del periodo citado, no dicho por la directiva)</div> : <div>Vencimiento: no determinado</div>}{promise.fulfillment_criteria ? <div>Criterio de cumplimiento: {promise.fulfillment_criteria}</div> : <div>Criterio de cumplimiento: no definido</div>}{promise.source_url ? <div>Fuente: <a className="underline" href={promise.source_url} rel="noopener noreferrer" target="_blank">{promise.source_url}</a>{promise.transcript_locator ? ` · localizador ${promise.transcript_locator}` : ''}</div> : null}{promise.flags?.length ? <div>Avisos: {promise.flags.map((f) => FLAG_LABELS[f] ?? f).join(', ')}</div> : null}{promise.status_reason ? <div>{promise.status_reason}</div> : null}</dl> : null}</div><div className="rounded-lg border border-gray-800 p-3 text-sm md:ml-auto md:min-w-56"><div className="text-xs uppercase text-gray-500">Objetivo / real</div><div className="mt-2 text-gray-200">{promise.metric ?? 'cualitativa'} {promise.operator ?? ''} {promise.target_value ?? NA} {promise.unit ?? ''}</div><div className="mt-1 text-teal-300">real {promise.actual_value ?? 'pendiente'}</div></div></div><MutationForm action={updateManagementExplanation.bind(null, ticker, promise.id)} className="mt-4 flex flex-col gap-2 md:flex-row" successMessage="Explicación guardada"><Input className="flex-1" defaultValue={promise.management_explanation ?? ''} name="explanation" placeholder="Explicación de la directiva o contexto del analista" required /><Button type="submit" variant="outline">Guardar explicación</Button></MutationForm></article>)}{!dashboard.promises.length ? <EmptyState title="Aún no hay promesas registradas." /> : null}</section>
{dashboard.legacy_excluded_from_score ? <p className="text-xs text-amber-300">{dashboard.legacy_excluded_from_score} promesa(s) importadas antes con objetivo numérico deducido automáticamente y sin procedencia quedan fuera de la puntuación: no son fiables.</p> : null}
<p className="text-xs text-gray-500">Método: {METHOD_ES[dashboard.method] ?? dashboard.method}. Los resultados dependen del mapeo de métricas canónicas y de los hechos reportados disponibles.</p>
  </main>;
}
