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
import { ExtractFromRegistry } from '@/components/research/ExtractFromRegistry';
import { commitmentsUiEnabled } from '@/lib/commitments-flag';
import { getSourceCoverage } from '@/lib/actions/source-coverage.actions';
import { addManagementPromiseNote, getManagementNotesByPromise, addManagementPromiseCheck, reviewManagementCandidate, createManagementPromise, extractManagementCandidates, extractManagementCandidatesFromUrl, getManagementCredibility, importManagementCallClaims, reconcileManagementCredibility, updateManagementExplanation } from '@/lib/actions/research-tools.actions';

function PromiseNotes({ ticker, promiseId, notes, truncated }: { ticker: string; promiseId: number; notes: { id: number; body: string; created_at: string | null }[] | null; truncated?: boolean }) {
  return (
    <div className="mt-4 rounded-lg border border-gray-800 p-3 text-sm">
      <div className="text-xs uppercase text-gray-500">Notas privadas (solo tú las ves)</div>
      {notes === null ? <p className="mt-1 text-xs text-gray-500">No se pudieron cargar las notas.</p> : notes.length ? <ul className="mt-2 grid gap-1">{notes.map((n) => <li className="text-gray-300" key={n.id}><span className="text-xs text-gray-500">{(n.created_at ?? '').slice(0, 10)} · </span>{n.body}</li>)}</ul> : <p className="mt-1 text-xs text-gray-500">Sin notas.</p>}{truncated ? <p className="mt-2 text-xs text-amber-300">Lista parcial: hay más de 500 notas en esta empresa y solo se cargan las más recientes. Puede haber notas antiguas de esta promesa que no se ven aquí.</p> : null}
      <MutationForm action={addManagementPromiseNote.bind(null, ticker, promiseId)} className="mt-2 flex flex-col gap-2 md:flex-row" resetOnSuccess successMessage="Nota guardada"><Input className="flex-1" name="body" aria-label="Nota privada" placeholder="Nota privada (no es evidencia ni cambia el estado)" required /><Button type="submit" variant="outline">Guardar nota</Button></MutationForm>
    </div>
  );
}

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
  mercado_o_tercero_mencionado: 'menciona mercado o terceros; revisar que el compromiso sea de la directiva',
  due_year_inferred: 'año del plazo inferido de la fecha de la llamada, no dicho por la directiva',
};

const SOURCE_CHECK_LABELS: Record<string, string> = {
  header_matches: 'se encontró el ticker y la fecha indicados en la cabecera del documento (no prueba que sea la llamada correcta ni que la fuente sea oficial)',
  header_date_differs: 'AVISO: la fecha indicada no aparece en la cabecera del documento; revisa que sea la llamada correcta',
  header_unreadable: 'cabecera ilegible: empresa y fecha sin comprobar contra el documento',
  not_checked: 'documento no comprobado (texto aportado a mano)',
};

const OUTCOME_LABELS: Record<string, string> = {
  unknown: 'desconocido',
  not_verifiable: 'no verificable',
  insufficient_evidence: 'evidencia insuficiente',
  met: 'cumplido según quien registra (evidencia aportada)',
  partially_met: 'parcialmente cumplido según quien registra (evidencia aportada)',
  not_met: 'no cumplido según quien registra (evidencia aportada)',
};

const DUE_STATE_LABELS: Record<string, string> = {
  no_due_date: 'sin vencimiento determinado',
  pending: 'plazo pendiente',
  overdue_unverified: 'plazo vencido SIN comprobar: no equivale a incumplido',
  checked: 'comprobado por el usuario con evidencia aportada (sin verificación automática)',
};

const DATE_BASIS_LABELS: Record<string, string> = {
  call_date: 'fecha de la llamada (indicada al registrar)',
  user_entered: 'fecha introducida por quien registra, no verificada',
  registered_at: 'fecha de alta en el sistema, NO la de la llamada',
};

const DUE_BASIS_LABELS: Record<string, string> = {
  year_end_inferred_from_call_year: 'fin del año de la llamada (inferido; la directiva no dijo la fecha)',
  year_end_hint: 'fin del año citado en la frase; el día exacto es orientativo',
  quarter_end_hint: 'fin del trimestre citado en la frase; el día exacto es orientativo',
};

const GRADE_LABELS: Record<string, string> = {
  high: 'alta',
  mixed: 'mixta',
  low: 'baja',
  insufficient_history: 'historial insuficiente',
};
const METHOD_ES: Record<string, string> = {
  'resolved promises: met=1, partial=0.5, missed=0': 'solo promesas con objetivo registrado por una persona y resueltas contra hechos canónicos: cumplida = 1, parcial = 0,5, fallida = 0. Pocas promesas resueltas = puntuación orientativa, sin fiabilidad estadística. Los candidatos sugeridos y las promesas con objetivo deducido automáticamente no puntúan',
};

function label(value: string | null | undefined): string {
  if (!value) return '—';
  return STATUS_LABELS[value] ?? value.replaceAll('_', ' ');
}

export default async function ManagementCredibilityPage({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  const dashboard = await getManagementCredibility(ticker);
  const uiOn = commitmentsUiEnabled();
  const notesData = uiOn ? await getManagementNotesByPromise(ticker).catch(() => null) : null;
  const coverage = uiOn ? await getSourceCoverage().catch(() => null) : null;
  const coverageCompany = coverage?.status === 'ok' ? coverage.report.companies.find((c) => c.ticker === ticker) : undefined;
  const registrySources = !uiOn || coverage === null || coverage.status !== 'ok' || coverageCompany === undefined ? null : (coverageCompany.transcript_sources ?? []);
  const outOfUniverse = uiOn && coverage?.status === 'ok' && coverageCompany === undefined;
    return <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6"><PageHeader actions={<div className="flex flex-wrap gap-2"><MutationForm action={importManagementCallClaims.bind(null, ticker)} successMessage="Afirmaciones de la llamada importadas"><Button className="h-auto whitespace-normal py-2 text-center" type="submit" variant="outline"><UploadCloud className="h-4 w-4" />Importar afirmaciones de la llamada</Button></MutationForm><MutationForm action={reconcileManagementCredibility.bind(null, ticker)} successMessage="Promesas reconciliadas"><Button type="submit"><RefreshCcw className="h-4 w-4" />Reconciliar</Button></MutationForm></div>} back={<Button asChild className="min-h-[44px] sm:min-h-0" size="sm" variant="ghost"><Link href={`/research/${ticker}`}><ArrowLeft className="h-4 w-4" />Workspace de {ticker}</Link></Button>} description="Registra promesas fechadas y recóncilialas con los hechos financieros canónicos." kicker="Responsabilidad de la directiva" title="Credibilidad de la directiva" />
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 2xl:grid-cols-8">{[['Puntuación', formatPercent(dashboard.score, { digits: 0 })], ['Calificación', GRADE_LABELS[dashboard.grade] ?? dashboard.grade], ['Abiertas', dashboard.counts.open], ['Registradas (sin sugeridos)', dashboard.counts.registered ?? dashboard.counts.total], ['Sugeridos, sin verificar', dashboard.counts.candidate ?? 0], ['Cumplidas', dashboard.counts.met], ['Parciales', dashboard.counts.partial], ['Fallidas', dashboard.counts.missed]].map(([label, value]) => <Stat key={String(label)} label={String(label)} size="sm" value={value} />)}</section>
    {uiOn ? (<MutationForm action={extractManagementCandidatesFromUrl.bind(null, ticker)} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Candidatos extraídos de la fuente (sin verificar)">
<h2 className="font-semibold text-gray-100">Extraer candidatos desde una URL oficial</h2><p className="mt-1 text-xs text-gray-500">Descarga un PDF de transcripción solo desde dominios de relaciones con inversores autorizados y comprueba que la cabecera no contradiga la empresa ni la fecha. Que el dominio sea oficial no prueba que el documento sea de esta empresa o llamada: indica la fecha de la llamada tú.</p><div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2"><Input name="call_date" required type="date" /><Input name="source_url" placeholder="https://… (PDF de transcripción)" required type="url" /><Button className="w-fit" type="submit">Extraer desde URL</Button></div></MutationForm>) : null}
    {uiOn ? (<MutationForm action={extractManagementCandidates.bind(null, ticker)} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Candidatos extraídos (sin verificar)">
<h2 className="font-semibold text-gray-100">Extraer candidatos de una transcripción</h2><p className="mt-1 text-xs text-gray-500">Reglas deterministas, sin IA. Solo propone frases de la directiva con verbo de futuro y dato comprobable; no se guarda la transcripción, solo la cita corta. Un candidato no es una promesa confirmada ni se marca cumplido o fallido sin evidencia.</p><div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2"><Textarea className="sm:col-span-2" name="transcript_text" placeholder="Texto de la transcripción oficial" required /><Input name="call_date" required type="date" /><Input name="source_url" placeholder="URL oficial de la transcripción (https://…)" required type="url" /><Button className="w-fit" type="submit">Extraer candidatos</Button></div></MutationForm>) : null}
    {uiOn ? <ExtractFromRegistry outOfUniverse={outOfUniverse} sources={registrySources} ticker={ticker} /> : null}
    <MutationForm action={createManagementPromise.bind(null, ticker)} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Promesa registrada">
<h2 className="font-semibold text-gray-100">Registrar una promesa</h2><div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"><Textarea className="md:col-span-3" name="promise" placeholder="Promesa o guidance exacta de la directiva" required /><Input name="promise_date" required type="date" /><Input name="expected_period" placeholder="FY2027 o Q4 2026" required /><Input name="metric" placeholder="Métrica canónica (opcional)" /><select className="h-9 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200" defaultValue="" name="operator"><option value="">Cualitativa / sin objetivo</option>{['>', '>=', '<', '<=', '=='].map((item) => <option key={item}>{item}</option>)}</select><Input name="target_value" placeholder="Valor objetivo" step="any" type="number" /><Input name="unit" placeholder="Unidad" /><Input name="source_document_id" placeholder="ID del documento fuente" type="number" min="1" /><Button className="w-fit" type="submit">Registrar promesa</Button></div></MutationForm>
        <section className="grid gap-4">{dashboard.promises.map((promise) => <article className="min-w-0 max-w-full [overflow-wrap:anywhere] rounded-xl border border-gray-800 bg-surface-1 p-5" key={promise.id}>
<div className="flex flex-col gap-3 md:flex-row md:items-start"><div><div className="flex flex-wrap items-center gap-2"><Badge className={promise.status === 'met' ? 'border-teal-800 text-teal-300' : promise.status === 'missed' ? 'border-red-900 text-red-300' : promise.status === 'partial' ? 'border-amber-900 text-amber-300' : ''} variant="outline">{promise.legacy_heuristic_target ? 'veredicto no verificado' : label(promise.status)}</Badge>{promise.legacy_heuristic_target ? <Badge className="border-amber-900 text-amber-300" variant="outline">objetivo deducido, no fiable</Badge> : null}<span className="text-xs text-gray-500">prometida {promise.promise_date} · esperada {promise.expected_period}</span></div><h2 className="mt-3 font-semibold leading-6 text-gray-100">{promise.quote_literal ? `“${promise.quote_literal}”` : promise.promise}</h2>{promise.quote_literal || promise.speaker || promise.source_url ? <dl className="mt-3 grid gap-1 text-xs text-gray-400"><div>{promise.speaker ?? 'hablante no registrado'}{promise.speaker_role ? `, ${promise.speaker_role}` : ''}</div>{promise.call_date ? <div>Llamada: {promise.call_date} ({DATE_BASIS_LABELS[promise.date_basis ?? ''] ?? 'base de fecha no registrada'})</div> : <div>Fecha de la llamada: no registrada</div>}{promise.due_date ? <div>Vencimiento orientativo: {promise.due_date} (derivado del periodo citado, no dicho por la directiva)</div> : <div>Vencimiento: no determinado</div>}{promise.due_basis && DUE_BASIS_LABELS[promise.due_basis] ? <div>Base del vencimiento: {DUE_BASIS_LABELS[promise.due_basis]}</div> : null}{promise.support_quote ? <div>Contexto del documento (frase anterior, NO es el compromiso): <span className="italic">“{promise.support_quote}”</span></div> : null}{promise.fulfillment_criteria ? <div>Criterio de cumplimiento: {promise.fulfillment_criteria}</div> : <div>Criterio de cumplimiento: no definido</div>}{promise.source_url ? <div>Fuente: <a className="underline" href={promise.source_url} rel="noopener noreferrer" target="_blank">{promise.source_url}</a>{promise.transcript_locator ? ` · localizador ${promise.transcript_locator}` : ''}</div> : null}{promise.source_check ? <div>Comprobación de la fuente: {SOURCE_CHECK_LABELS[promise.source_check] ?? promise.source_check}</div> : null}{promise.flags?.length ? <div>Avisos: {promise.flags.map((f) => FLAG_LABELS[f] ?? f).join(', ')}</div> : null}{promise.status_reason ? <div>{promise.status_reason}</div> : null}</dl> : null}</div><div className="rounded-lg border border-gray-800 p-3 text-sm md:ml-auto md:min-w-56"><div className="text-xs uppercase text-gray-500">Objetivo / real</div><div className="mt-2 text-gray-200">{promise.metric ?? 'cualitativa'} {promise.operator ?? ''} {promise.target_value ?? NA} {promise.unit ?? ''}</div><div className="mt-1 text-teal-300">real {promise.actual_value ?? 'pendiente'}</div></div></div>{uiOn ? (<div className="mt-4 rounded-lg border border-gray-800 p-3 text-sm"><div className="text-xs uppercase text-gray-500">Qué ocurrió después</div>{promise.due_state ? <p className="mt-1 text-xs text-gray-400">{DUE_STATE_LABELS[promise.due_state] ?? promise.due_state}</p> : null}{promise.checks?.length ? <ul className="mt-2 grid gap-2">{promise.checks.map((check) => <li className="text-gray-200" key={check.id}><span className="text-xs text-gray-500">{check.checked_on} · </span>{OUTCOME_LABELS[check.outcome] ?? check.outcome}{check.summary ? ` — ${check.summary}` : ''}{check.evidence_excerpt ? <blockquote className="mt-1 border-l border-gray-700 pl-2 text-xs text-gray-400">“{check.evidence_excerpt}”{check.evidence_url ? <> · <a className="underline" href={check.evidence_url} rel="noopener noreferrer" target="_blank">fuente</a></> : null}{check.evidence_date ? ` (${check.evidence_date})` : ''}</blockquote> : null}<div className="text-xs text-gray-500">Declarado por un usuario de este espacio de trabajo{check.declared_at ? ` el ${check.declared_at.slice(0, 10)}` : ''}; URL y extracto no se comprueban de forma independiente.</div></li>)}</ul> : <p className="mt-1 text-xs text-gray-500">Aún sin comprobaciones registradas.</p>}{!uiOn ? null : promise.status === 'candidate' ? (<MutationForm action={reviewManagementCandidate.bind(null, ticker, promise.id)} className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2" resetOnSuccess successMessage="Candidato revisado: ya es un compromiso en seguimiento"><p className="text-xs text-amber-300 sm:col-span-2">Candidato sin revisar. Compara la cita, el contexto, la fecha y la fuente con el documento original y define cómo se comprobará. Esto es una declaración tuya; no se verifica de forma automática.</p><Textarea className="sm:col-span-2" name="fulfillment_criteria" aria-label="Criterio de cumplimiento" placeholder="Criterio de cumplimiento (qué hecho concreto y fecha lo probaría)" required /><Input name="due_date" type="date" /><label className="flex items-center gap-2 text-xs text-gray-300"><input name="confirmed_source_checked" required type="checkbox" />He revisado la cita, el contexto, la fecha y la fuente en el documento original</label><Button className="w-fit" type="submit" variant="outline">Pasar a seguimiento</Button></MutationForm>) : (<MutationForm action={addManagementPromiseCheck.bind(null, ticker, promise.id)} className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2" resetOnSuccess successMessage="Comprobación registrada"><select className="h-9 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200" defaultValue="not_verifiable" name="outcome">{Object.entries(OUTCOME_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select><Input name="checked_on" required type="date" /><Input className="sm:col-span-2" name="summary" aria-label="Resumen de la comprobación" placeholder="Resumen (obligatorio si no hay veredicto)" /><Input name="evidence_url" aria-label="URL https de la evidencia" placeholder="URL https de la evidencia" type="url" /><Input name="evidence_date" type="date" /><Textarea className="sm:col-span-2" name="evidence_excerpt" aria-label="Extracto literal de la evidencia" placeholder="Extracto literal de la evidencia que prueba el criterio" /><Button className="w-fit" type="submit" variant="outline">Registrar comprobación</Button></MutationForm>)}{uiOn ? <p className="mt-2 text-xs text-gray-500">Cumplido, parcial o no cumplido exigen criterio definido, URL https y extracto. Un enlace sin contenido que pruebe el criterio no cuenta.</p> : null}</div>) : null}{uiOn ? <PromiseNotes notes={notesData === null ? null : notesData.notes[String(promise.id)] ?? []} truncated={notesData?.truncated} promiseId={promise.id} ticker={ticker} /> : null}<MutationForm action={updateManagementExplanation.bind(null, ticker, promise.id)} className="mt-4 flex flex-col gap-2 md:flex-row" successMessage="Explicación guardada"><Input className="flex-1" defaultValue={promise.management_explanation ?? ''} name="explanation" aria-label="Explicación de la directiva o contexto del analista" placeholder="Explicación de la directiva o contexto del analista" required /><Button type="submit" variant="outline">Guardar explicación</Button></MutationForm></article>)}{!dashboard.promises.length ? <EmptyState title="Aún no hay promesas registradas." /> : null}</section>
{dashboard.legacy_excluded_from_score ? <p className="text-xs text-amber-300">{dashboard.legacy_excluded_from_score} promesa(s) importadas antes con objetivo numérico deducido automáticamente y sin procedencia quedan fuera de la puntuación: no son fiables.</p> : null}
<p className="text-xs text-gray-500">Método: {METHOD_ES[dashboard.method] ?? dashboard.method}. Los resultados dependen del mapeo de métricas canónicas y de los hechos reportados disponibles.</p>
  </main>;
}
