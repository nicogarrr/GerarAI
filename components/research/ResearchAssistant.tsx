'use client';

import { useEffect, useState, type FormEvent } from 'react';
import { BookOpen, ExternalLink, LockKeyhole, Search } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Panel } from '@/components/ui/panel';
import { Textarea } from '@/components/ui/textarea';
import { askResearchAssistantAction, getGuideContextAction } from '@/lib/research/assistant-actions';
import { safeAssistantSourceUrl, type AssistantMode, type AssistantResponse, type AssistantCitationKind, type AssistantSectionKey, type GuideContext } from '@/lib/research/assistant-contract';
import { t } from '@/lib/i18n/t';
import { formatUserDateTime } from '@/lib/format';

const SECTION_LABELS: Record<AssistantSectionKey, string> = {
  facts: 'Hechos', calculations: 'Cálculos', hypotheses: 'Hipótesis', inferences: 'Inferencias',
  contradictions: 'Contradicciones', insufficient_data: 'Datos insuficientes', conclusion: 'Conclusión',
};
const CITATION_LABELS: Record<AssistantCitationKind, string> = {
  news_event: 'Noticia atribuida', financial_fact: 'Dato financiero', document_chunk: 'Documento',
  claim_evidence: 'Evidencia de afirmación', market_observation: 'Observación de mercado', thesis_record: 'Tesis guardada',
};

/**
 * Copy de una respuesta o sección VACÍA.
 *
 * El contrato permite `answer: ''` y `body: ''`: no es un dato que falte, es
 * texto que el asistente no escribió, y un «Sin datos» a secas no dice si falta
 * la respuesta, si la evidencia no daba para una o si el modelo se quedó mudo.
 * Se nombra el caso y se dice dónde está la información que sí hay.
 */
function emptyAnswerCopy(status: 'answered' | 'insufficient_data'): string {
  return status === 'insufficient_data'
    ? 'El asistente no ha escrito una conclusión: la evidencia disponible no permite una confirmada. Lo que falta está enumerado en «Datos que faltan», más abajo.'
    : 'El asistente ha devuelto la respuesta sin texto: no hay nada que mostrar como respuesta. Lo que sí ha enviado son las secciones y las citas de abajo.';
}

function emptySectionCopy(status: 'answered' | 'insufficient_data'): string {
  return status === 'insufficient_data'
    ? 'Sección sin cuerpo: el asistente no ha escrito nada aquí porque la evidencia no daba para tanto.'
    : 'Sección sin cuerpo: el asistente la ha enviado vacía. Sin texto no hay nada que leer.';
}

function Citation({ citation }: { citation: AssistantResponse['citations'][number] }) {
  const url = safeAssistantSourceUrl(citation.url);
  return <li className="min-w-0 rounded-lg border border-gray-700/50 bg-black/20 p-3 text-xs text-gray-400">
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline">{CITATION_LABELS[citation.kind] ?? 'Fuente sin clasificar'}</Badge>
      {url ? <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-w-0 items-center gap-1 break-all text-teal-300 underline underline-offset-2 hover:text-teal-200">{citation.source || 'Fuente sin nombre'}<ExternalLink aria-hidden className="h-3 w-3 shrink-0" /></a> : <span className="min-w-0 break-all text-gray-200">{citation.source || 'Fuente sin nombre'}</span>}
    </div>
    <div className="mt-2 break-all">Fecha de referencia: {citation.as_of || t('signals.noDate')}</div>
    {citation.excerpt ? <details className="mt-2"><summary className="cursor-pointer text-gray-500 hover:text-gray-300">Extracto original</summary><p className="mt-2 whitespace-pre-wrap break-words text-gray-300">{citation.excerpt}</p></details> : null}
  </li>;
}

export default function ResearchAssistant({ initialMode = 'explore', initialTicker, initialReviewId }: {
  initialMode?: AssistantMode; initialTicker?: string; initialReviewId?: number;
}) {
  const [mode, setMode] = useState<AssistantMode>(initialMode);
  const [ticker, setTicker] = useState(initialTicker ?? '');
  const [question, setQuestion] = useState('');
  const [reviewId, setReviewId] = useState<number | undefined>(initialMode === 'guide' ? initialReviewId : undefined);
  const [context, setContext] = useState<GuideContext | null>(null);
  const [contextError, setContextError] = useState(false);
  const [result, setResult] = useState<AssistantResponse | null>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  // Contexto opcional: su fallo no impide preguntar con ticker, sin ticket.
  useEffect(() => {
    const value = ticker.trim().toUpperCase();
    setContext(null);
    setContextError(false);
    if (mode !== 'guide' || !value) return;
    let live = true;
    // Espera a que termine de escribir: no consultar A, AA y AAP al teclear AAPL.
    const timer = setTimeout(() => {
      getGuideContextAction(value).then((data) => {
        if (live) setContext(data);
      }).catch(() => { if (live) setContextError(true); });
    }, 350);
    return () => { live = false; clearTimeout(timer); };
  }, [mode, ticker]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = question.trim();
    if (clean.length < 3 || clean.length > 2000 || (mode === 'guide' && !ticker.trim())) return;
    setPending(true);
    setError('');
    setResult(null);
    try {
      const response = await askResearchAssistantAction({ mode, question: clean, ...(ticker.trim() ? { ticker: ticker.trim().toUpperCase() } : {}), ...(mode === 'guide' && reviewId && context?.ticker.toUpperCase() === ticker.trim().toUpperCase() && context.open_reviews.some((review) => review.id === reviewId) ? { review_id: reviewId } : {}) });
      setResult(response.status === 'insufficient_data'
        ? { ...response, sections: response.sections.map((s) => (s.body?.trim() === 'Datos insuficientes' ? { ...s, body: '' } : s)) }
        : response);
    } catch {
      setError('No se pudo obtener la respuesta. Reintenta; no se ha modificado nada.');
    } finally {
      setPending(false);
    }
  }

  return <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)]">
    <div className="min-w-0 space-y-5">
      <Panel title="Pregunta" icon={Search}>
        <form onSubmit={submit} className="space-y-4">
          <fieldset className="flex flex-wrap gap-2" disabled={pending}>
            <legend className="mb-2 text-sm text-gray-300">Modo</legend>
            {(['explore', 'guide'] as const).map((item) => <label key={item} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${mode === item ? 'border-teal-600 bg-teal-950/30 text-teal-200' : 'border-gray-700 text-gray-400'}`}><input type="radio" name="mode" checked={mode === item} onChange={() => { setMode(item); setResult(null); setReviewId(undefined); }} /><span>{item === 'explore' ? 'Explorar' : 'Guía de empresa'}</span></label>)}
          </fieldset>
          <div>
            <label htmlFor="assistant-ticker" className="mb-1 block text-sm text-gray-300">Ticker {mode === 'guide' ? '(obligatorio)' : '(opcional)'}</label>
            <input id="assistant-ticker" value={ticker} onChange={(event) => { setTicker(event.target.value); setReviewId(undefined); setResult(null); }} required={mode === 'guide'} disabled={pending} autoComplete="off" placeholder="Por ejemplo, AAPL" className="min-h-11 w-full rounded-lg border border-gray-700 bg-surface-0 px-3 text-base text-gray-100 placeholder:text-gray-500 focus:border-teal-600 focus:outline-none sm:text-sm" />
          </div>
          <div>
            <label htmlFor="assistant-question" className="mb-1 block text-sm text-gray-300">Pregunta</label>
            <Textarea id="assistant-question" value={question} onChange={(event) => { setQuestion(event.target.value); setResult(null); }} required minLength={3} maxLength={2000} disabled={pending} placeholder="¿Qué sabemos, qué falta y qué contradicciones hay?" className="min-h-28 bg-surface-0 text-base text-gray-100 sm:text-sm" />
            <p className="mt-1 text-right text-xs text-gray-500">{question.length}/2000</p>
          </div>
          <Button type="submit" disabled={pending || question.trim().length < 3 || (mode === 'guide' && !ticker.trim())} className="min-h-11 w-full sm:w-auto"><BookOpen aria-hidden />{pending ? 'Analizando…' : 'Preguntar'}</Button>
        </form>
      </Panel>
      <section aria-live="polite" aria-busy={pending}>
        {error ? <p role="alert" className="rounded-xl border border-amber-800 bg-amber-950/20 p-4 text-sm text-amber-200">{error}</p> : null}
        {result ? <Panel title="Respuesta" icon={LockKeyhole} description={`Modo ${result.mode === 'guide' ? 'guía' : 'explorar'} · Sin escritura: solo lectura, no modifica nada`}>
          {result.status === 'insufficient_data' ? <div role="status" className="mb-4 rounded-lg border border-amber-800 bg-amber-950/20 p-3 text-sm text-amber-200"><strong>Datos insuficientes</strong><p className="mt-1">La evidencia disponible no permite una conclusión confirmada.</p></div> : null}
          <p className="whitespace-pre-wrap break-words text-sm leading-7 text-gray-200">{result.answer?.trim() ? result.answer : emptyAnswerCopy(result.status)}</p>
          {result.sections.length ? <div className="mt-5 space-y-2">{result.sections.map((section, index) => <details key={`${section.key}-${index}`} className="rounded-lg border border-gray-700/50 bg-black/20" open={section.key === 'conclusion' && result.status === 'answered'}><summary className="min-h-11 cursor-pointer px-3 py-3 text-sm font-semibold text-gray-200">{SECTION_LABELS[section.key] ?? 'Sección sin clasificar'}</summary><div className="border-t border-gray-800 px-3 py-3"><p className="whitespace-pre-wrap break-words text-sm leading-6 text-gray-300">{section.body?.trim() ? section.body : emptySectionCopy(result.status)}</p>{section.citation_ids.length ? <p className="mt-2 break-words text-xs text-gray-500">Citas: {section.citation_ids.length}</p> : <p className="mt-2 text-xs text-gray-500">Sin citas para esta sección</p>}</div></details>)}</div> : <p className="mt-4 text-sm text-gray-500">Sin secciones adicionales</p>}
          {result.missing_data.length || result.status === 'insufficient_data' ? <div className="mt-5 rounded-lg border border-amber-800/60 p-3"><h3 className="text-sm font-semibold text-amber-200">Datos que faltan</h3>{result.missing_data.length ? <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-300">{result.missing_data.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="mt-2 text-sm text-gray-400">Sin datos sobre qué información falta.</p>}</div> : null}
          {result.suggested_next_steps.length ? <div className="mt-5"><h3 className="text-sm font-semibold text-gray-200">Próximos pasos sugeridos</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-400">{result.suggested_next_steps.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
          <div className="mt-5 border-t border-gray-800 pt-4"><h3 className="text-sm font-semibold text-gray-200">Citas y fuentes ({result.citations.length})</h3>{result.citations.length ? <ul className="mt-3 grid min-w-0 gap-2">{result.citations.map((citation, index) => <Citation key={`${citation.id}-${index}`} citation={citation} />)}</ul> : <p className="mt-2 text-sm text-gray-500">Sin datos de fuentes.</p>}</div>
        </Panel> : !error && !pending ? <p className="rounded-xl border border-gray-800 bg-surface-1 p-5 text-sm text-gray-500">Sin respuesta todavía. Formula una pregunta para ver fuentes y lagunas de evidencia.</p> : null}
      </section>
    </div>
    <aside className="min-w-0 space-y-4 lg:pt-0">
      <Panel title="Contexto de guía">
        {mode === 'explore' ? <p className="text-sm text-gray-500">Selecciona Guía de empresa para ver revisiones y noticias disponibles.</p> : !ticker.trim() ? <p className="text-sm text-gray-500">Sin datos. Introduce un ticker.</p> : contextError ? <p className="text-sm text-amber-200">No se pudo cargar el contexto opcional. Puedes preguntar sin anclar una revisión.</p> : !context ? <p className="text-sm text-gray-500">Cargando contexto…</p> : <div className="space-y-5 text-sm">
          <div><label htmlFor="assistant-review" className="block font-semibold text-gray-200">Revisión abierta (opcional)</label><select id="assistant-review" value={context.open_reviews.some((review) => review.id === reviewId) ? reviewId : ''} onChange={(event) => { setReviewId(event.target.value ? Number(event.target.value) : undefined); setResult(null); }} className="mt-2 min-h-11 w-full rounded-lg border border-gray-700 bg-surface-0 px-2 text-gray-200"><option value="">Sin revisión anclada</option>{context.open_reviews.map((review) => <option key={review.id} value={review.id}>#{review.id} · {review.summary}</option>)}</select><p className="mt-1 text-xs text-gray-500">La pregunta no acepta ni cierra la revisión.</p></div>
          <div><h3 className="font-semibold text-gray-200">Últimas noticias atribuidas</h3>{context.latest_news.length ? <ul className="mt-2 space-y-2">{context.latest_news.map((news) => <li key={news.id} className="rounded-lg border border-gray-800 p-2"><Badge variant="outline">Noticia atribuida</Badge><p className="mt-1 break-words text-gray-300">{safeAssistantSourceUrl(news.source_url) ? <a href={safeAssistantSourceUrl(news.source_url)!} target="_blank" rel="noopener noreferrer" className="text-teal-300 underline">{news.title}</a> : news.title}</p><p className="mt-1 text-xs text-gray-500">{news.source || 'Fuente sin datos'} · {news.date_source === 'gdelt_first_seen' ? 'Detectada' : news.date_source === 'ingested_at_fallback' ? 'Incorporada' : news.date_source === 'source' ? 'Publicada' : 'Fecha registrada'}: {news.date ? formatUserDateTime(news.date) : t('signals.noDate')}</p></li>)}</ul> : <p className="mt-2 text-gray-500">Sin datos de noticias.</p>}</div>
          {context.missing_data.length ? <div><h3 className="font-semibold text-gray-200">Datos que faltan en el contexto</h3><ul className="mt-2 list-disc pl-5 text-gray-400">{context.missing_data.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
        </div>}
      </Panel>
    </aside>
  </div>;
}
