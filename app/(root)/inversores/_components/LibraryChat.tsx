'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { markdownComponents } from '@/components/research/ThesisMarkdown';
import { askKnowledge, type LibraryAnswer } from '@/lib/actions/knowledge-chat.actions';
import { analysisToText, isSubmitShortcut, SUGGESTED_QUESTIONS, type CitedPoint } from '@/lib/knowledge/analysis';

type Turn = { id: number; question: string; analysis: boolean; result: LibraryAnswer | null; error: string | null };
type Citation = LibraryAnswer['answers'][number]['citation'];

function citationLine(cite: Citation) {
  const parts = [cite.author ?? 'Autor no registrado', cite.title];
  if (cite.page_number !== null) parts.push(`Página ${cite.page_number}`);
  parts.push(`Fragmento ${cite.chunk_index + 1}`);
  if (cite.publication_date) parts.push(cite.publication_date);
  return parts.join(' · ');
}

function links(cite: Citation) {
  const reader = cite.document_type === 'fund_letter' ? `/inversores/cartas/${cite.document_id}?pagina=${Math.floor(cite.chunk_index / 8) + 1}#chunk-${cite.chunk_id}` : `/knowledge?document=${cite.document_id}`;
  const original = cite.source_url && /^https?:\/\//i.test(cite.source_url) ? `${cite.source_url}${cite.source_url.includes('#') || cite.page_number === null ? '' : `#page=${cite.page_number}`}` : null;
  return <div className="mt-2 flex flex-wrap gap-4 text-sm text-lime-300"><Link href={reader}>Ver fragmento</Link>{original && <a href={original} target="_blank" rel="noreferrer">Original</a>}</div>;
}

function Cited({ point }: { point: CitedPoint }) {
  return <div className="min-w-0">
    <p className="whitespace-pre-wrap break-words text-sm">{point.nombre && <strong>{point.nombre}: </strong>}{point.text}</p>
    <blockquote className="mt-1 min-w-0 break-words border-l-2 border-lime-300 pl-3 text-sm leading-6 text-gray-300"><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{point.citation.quote}</ReactMarkdown></blockquote>
    <p className="mt-1 text-xs text-gray-500">{citationLine(point.citation)}</p>
    {links(point.citation)}
  </div>;
}

function Analysis({ result }: { result: LibraryAnswer }) {
  const a = result.analysis;
  if (!a) return null;
  return <div className="flex flex-col gap-4">
    <section><h3 className="text-sm font-semibold text-lime-300">Tesis</h3>
      <ol className="mt-2 flex list-decimal flex-col gap-3 pl-5">{a.tesis.map((p, i) => <li key={i}><Cited point={p} /></li>)}</ol></section>
    <section><h3 className="text-sm font-semibold text-lime-300">Qué me haría equivocarme</h3><div className="mt-2"><Cited point={a.error} /></div></section>
    <section><h3 className="text-sm font-semibold text-lime-300">Escenarios</h3>
      <ul className="mt-2 flex flex-col gap-2">{a.escenarios.map((s, i) => <li key={i} className="text-sm"><strong>{s.nombre}</strong> · {s.probabilidad} %<span className="block text-gray-400">Disparador: {s.disparador}</span></li>)}</ul>
      <p className="mt-1 text-xs text-gray-500">{a.probabilidades}</p></section>
    <section><h3 className="text-sm font-semibold text-lime-300">Modelos mentales</h3>
      <ul className="mt-2 flex flex-col gap-3">{a.modelos.map((p, i) => <li key={i}><Cited point={p} /></li>)}</ul></section>
    <section><h3 className="text-sm font-semibold text-lime-300">Lo que no sé</h3>
      <ul className="mt-2 list-disc pl-5 text-sm text-gray-300">{a.no_se.map((t, i) => <li key={i}>{t}</li>)}</ul></section>
    <p className="text-xs text-amber-300">{a.aviso}</p>
  </div>;
}

function Answer({ result }: { result: LibraryAnswer }) {
  return <div className="flex flex-col gap-4">
    {result.message && <p className="text-sm text-gray-400">{result.message}</p>}
    {result.retrieval === 'solo_texto' && <p className="text-xs text-gray-500">Búsqueda por texto. Prueba también términos del idioma original.</p>}
    <Analysis result={result} />
    {result.answers.map((answer, index) => <article key={`${answer.citation.chunk_id}-${index}`} className="min-w-0 border-t border-gray-800 pt-3">
      {answer.text && <p className="mb-2 whitespace-pre-wrap break-words text-sm">{answer.text}</p>}
      <blockquote className="min-w-0 break-words border-l-2 border-lime-300 pl-3 text-sm leading-6 text-gray-300"><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{answer.citation.quote}</ReactMarkdown></blockquote>
      <p className="mt-2 text-xs text-gray-500">{citationLine(answer.citation)}</p>
      {links(answer.citation)}
    </article>)}
  </div>;
}

export function LibraryChat({ scope = 'letters', authors = [] }: { scope?: 'letters' | 'library'; authors?: string[] }) {
  const pathname = usePathname();
  const page = pathname ? { path: pathname, label: scope === 'letters' ? 'Cartas de inversores' : 'Biblioteca', ticker: null } : null;
  const [question, setQuestion] = useState('');
  const [author, setAuthor] = useState('');
  const [analysis, setAnalysis] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<number | null>(null);

  async function ask(text: string) {
    const trimmed = text.trim();
    if (busy || trimmed.length < 3) return;
    const id = Date.now();
    setBusy(true); setQuestion('');
    try {
      const result = await askKnowledge(trimmed, scope, author, analysis ? 'analisis' : 'respuesta', page);
      setTurns(prev => [{ id, question: trimmed, analysis, result, error: null }, ...prev]);
    } catch {
      setTurns(prev => [{ id, question: trimmed, analysis, result: null, error: 'No se pudo consultar la biblioteca. Inténtalo de nuevo.' }, ...prev]);
    } finally { setBusy(false); }
  }
  async function copy(turn: Turn) {
    const a = turn.result?.analysis;
    const body = a ? analysisToText(a) : (turn.result?.answers ?? []).map(x => `${x.text ? `${x.text}\n` : ''}«${x.citation.quote}» (${citationLine(x.citation)})`).join('\n\n');
    try { await navigator.clipboard.writeText(`${turn.question}\n\n${body}`); setCopied(turn.id); } catch { setCopied(null); }
  }
  return <section aria-label="Preguntar a la biblioteca" className="flex min-w-0 flex-col gap-3 rounded-xl border border-gray-800 p-4">
    <h2 className="text-xl font-semibold">{scope === 'letters' ? 'Preguntar a las cartas' : 'Preguntar a la biblioteca'}</h2>
    <p className="text-xs text-amber-300">Doctrina, no datos actuales de empresas. Síntesis del modelo con citas; el original manda.</p>
    <form onSubmit={event => { event.preventDefault(); void ask(question); }} className="flex flex-col gap-3">
      {authors.length > 0 && <label className="text-sm">Autor
        <select value={author} onChange={event => setAuthor(event.target.value)} className="mt-1 block w-full rounded-lg border border-gray-700 bg-surface-1 p-2">
          <option value="">Todos los autores</option>{authors.map(name => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={analysis} onChange={event => setAnalysis(event.target.checked)} />Análisis estructurado (tesis, escenarios, modelos mentales)</label>
      <label className="text-sm" htmlFor={`library-question-${scope}`}>Pregunta</label>
      <textarea id={`library-question-${scope}`} value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (isSubmitShortcut(event)) { event.preventDefault(); void ask(question); } }} required minLength={3} maxLength={1200} rows={2} placeholder="¿Qué dice Buffett sobre las recompras?" className="w-full rounded-lg border border-gray-700 bg-surface-1 p-3 text-sm" />
      <div className="flex flex-wrap items-center gap-3">
        <button disabled={busy || question.trim().length < 3} className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-medium text-gray-950 disabled:opacity-50">{busy ? 'Consultando…' : 'Preguntar'}</button>
        <span className="text-xs text-gray-500">Ctrl + Enter para enviar</span>
      </div>
    </form>
    {turns.length === 0 && !busy && <div className="flex flex-wrap gap-2" aria-label="Preguntas sugeridas">
      {SUGGESTED_QUESTIONS.map(text => <button key={text} type="button" onClick={() => setQuestion(text)} className="rounded-full border border-gray-700 px-3 py-1 text-xs text-gray-300 hover:border-lime-300">{text}</button>)}
    </div>}
    <div aria-live="polite" className="flex flex-col gap-5">
      {busy && <p className="text-sm text-gray-400">{analysis ? 'Preparando el análisis (puede tardar hasta un minuto)…' : 'Consultando…'}</p>}
      {turns.map(turn => <div key={turn.id} className="flex min-w-0 flex-col gap-3 border-t border-gray-800 pt-4">
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm font-medium">{turn.question}{turn.analysis && <span className="ml-2 text-xs text-lime-300">Análisis</span>}</p>
          {turn.result && turn.result.answers.length + (turn.result.analysis ? 1 : 0) > 0 && <button type="button" onClick={() => void copy(turn)} className="shrink-0 text-xs text-lime-300">{copied === turn.id ? 'Copiado' : 'Copiar'}</button>}
        </div>
        {turn.error && <p role="alert" className="text-sm text-red-300">{turn.error}</p>}
        {turn.result && <Answer result={turn.result} />}
      </div>)}
    </div>
  </section>;
}
