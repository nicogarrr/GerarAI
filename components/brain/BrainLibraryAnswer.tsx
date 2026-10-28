
import Link from 'next/link';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { markdownComponents } from '@/components/research/ThesisMarkdown';
import { type LibraryAnswer } from '@/lib/actions/knowledge-chat.actions';
import { type CitedPoint } from '@/lib/knowledge/analysis';

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
  return <div className="mt-2 flex flex-wrap gap-4 text-sm text-teal-300 [&>a]:inline-flex [&>a]:min-h-11 [&>a]:items-center"><Link href={reader}>Ver fragmento</Link>{original && <a href={original} target="_blank" rel="noreferrer">Original</a>}</div>;
}

function Cited({ point }: { point: CitedPoint }) {
  return <div className="min-w-0">
    <p className="whitespace-pre-wrap break-words text-sm">{point.nombre && <strong>{point.nombre}: </strong>}{point.text}</p>
    <blockquote className="mt-1 min-w-0 break-words border-l-2 border-teal-300 pl-3 text-sm leading-6 text-gray-300"><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{point.citation.quote}</ReactMarkdown></blockquote>
    <p className="mt-1 text-xs text-gray-500">{citationLine(point.citation)}</p>
    {links(point.citation)}
  </div>;
}

function Analysis({ result }: { result: LibraryAnswer }) {
  const a = result.analysis;
  if (!a) return null;
  return <div className="flex flex-col gap-4">
    <section><h3 className="text-sm font-semibold text-teal-300">Tesis</h3>
      <ol className="mt-2 flex list-decimal flex-col gap-3 pl-5">{a.tesis.map((p, i) => <li key={i}><Cited point={p} /></li>)}</ol></section>
    <section><h3 className="text-sm font-semibold text-teal-300">Qué me haría equivocarme</h3><div className="mt-2"><Cited point={a.error} /></div></section>
    <section><h3 className="text-sm font-semibold text-teal-300">Escenarios</h3>
      <ul className="mt-2 flex flex-col gap-2">{a.escenarios.map((s, i) => <li key={i} className="text-sm"><strong>{s.nombre}</strong> · {s.probabilidad} %<span className="block text-gray-400">Disparador: {s.disparador}</span></li>)}</ul>
      <p className="mt-1 text-xs text-gray-500">{a.probabilidades}</p></section>
    <section><h3 className="text-sm font-semibold text-teal-300">Modelos mentales</h3>
      <ul className="mt-2 flex flex-col gap-3">{a.modelos.map((p, i) => <li key={i}><Cited point={p} /></li>)}</ul></section>
    <section><h3 className="text-sm font-semibold text-teal-300">Lo que no sé</h3>
      <ul className="mt-2 list-disc pl-5 text-sm text-gray-300">{a.no_se.map((t, i) => <li key={i}>{t}</li>)}</ul></section>
    <p className="text-xs text-amber-300">{a.aviso}</p>
  </div>;
}

export function BrainLibraryAnswer({ result }: { result: LibraryAnswer }) {
  return <div className="flex flex-col gap-4">
    {result.message && <p className="text-sm text-gray-400">{result.message}</p>}
    {result.retrieval === 'solo_texto' && <p className="text-xs text-gray-500">Búsqueda por texto. Prueba también términos del idioma original.</p>}
    <Analysis result={result} />
    {result.answers.map((answer, index) => <article key={`${answer.citation.chunk_id}-${index}`} className="min-w-0 border-t border-gray-800 pt-3">
      {answer.text && <p className="mb-2 whitespace-pre-wrap break-words text-sm">{answer.text}</p>}
      <blockquote className="min-w-0 break-words border-l-2 border-teal-300 pl-3 text-sm leading-6 text-gray-300"><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{answer.citation.quote}</ReactMarkdown></blockquote>
      <p className="mt-2 text-xs text-gray-500">{citationLine(answer.citation)}</p>
      {links(answer.citation)}
    </article>)}
  </div>;
}

