import { ArchivedThesisNotice } from '@/components/knowledge/ArchivedThesisNotice';
import { ExtractionRefresh } from '@/components/knowledge/ExtractionRefresh';
import { extractionResultText, hasDefaultCollections, noPrinciplesText } from '@/lib/knowledge/job-feedback';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/components/research/ThesisMarkdown';
import { LibraryChat } from '../inversores/_components/LibraryChat';
import type { Metadata } from 'next';
import Link from 'next/link';
import { BookOpen, Check, FileSearch, Library, Sparkles, UploadCloud, X } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { FileUploadInput } from '@/components/forms/FileUploadInput';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { PageHeader } from '@/components/ui/page-header';
import {
  createKnowledgeCollectionResult,
  decideKnowledgePrinciple,
  extractKnowledgePrinciples,
  getKnowledgeDocumentChunks,
  getKnowledgeLibrary,
  getKnowledgeDocument,
  installKnowledgeDefaults,
  mergeKnowledgePrinciple,
  reviseKnowledgePrincipleResult,
  setKnowledgeDocumentTicker,
  uploadKnowledgeDocumentResult,
} from '@/lib/actions/research-tools.actions';
import BackendOffline from '@/components/system/BackendOffline';
import { DeleteCollectionButton } from '@/components/knowledge/DeleteCollectionButton';
import { DeleteDocumentButton } from '@/components/knowledge/DeleteDocumentButton';
import { LibrarySearchForm } from '@/components/knowledge/LibrarySearchForm';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatDate, formatNumber, formatPercent, NA } from '@/lib/format';
import { t } from '@/lib/i18n/t';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
  title: 'Biblioteca de conocimiento',
  description:
    'Libros, cartas y casos de estudio separados de la evidencia de empresas, con principios de inversión aprobados por humanos y trazables.',
};

const KNOWLEDGE_PAGE_SIZE = 50;

type PageProps = { searchParams: Promise<{ document?: string; status?: string; tab?: string; documentOffset?: string; principleOffset?: string; q?: string }> };

/** Pestañas de la página. El estado vive en la URL (?tab=): los disparadores
 *  son enlaces, así que la vista se puede compartir, recargar y usar sin
 *  JavaScript, y sólo se envía al cliente el panel activo. */
const TABS = {
  biblioteca: 'biblioteca',
  principios: 'principios',
  subir: 'subir',
} as const;

type TabKey = (typeof TABS)[keyof typeof TABS];

const TAB_LABELS: Record<TabKey, string> = {
  biblioteca: 'Biblioteca',
  principios: 'Principios',
  subir: 'Subir',
};

function asTab(value: string | undefined): TabKey {
  return value === TABS.principios || value === TABS.subir ? value : TABS.biblioteca;
}

const PRINCIPLE_STATUS_LABELS: Record<string, string> = {
  '': 'todos',
  proposed: 'propuestos',
  approved: 'aprobados',
  rejected: 'rechazados',
  merged: 'fusionados',
  superseded: 'sustituidos',
};

/** Etiquetas en español para los estados persistidos por el backend */
const STATUS_LABELS: Record<string, string> = {
  queued: 'en cola',
  running: 'en curso',
  succeeded: 'completada',
  failed: 'fallida',
  pending: 'pendiente',
  processing: 'procesando',
  ready: 'lista',
  proposed: 'propuesto',
  approved: 'aprobado',
  rejected: 'rechazado',
  merged: 'fusionado',
  superseded: 'sustituido',
};

function label(value: string | null | undefined): string {
  if (!value) return NA;
  return STATUS_LABELS[value] ?? value.replaceAll('_', ' ');
}

/** Mismo vocabulario que el select de subida (KNOWLEDGE_DOCUMENT_TYPES del
 *  backend): la tabla y las tarjetas pintan la etiqueta, no la clave. */
const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  book: 'Libro',
  fund_letter: 'Carta de fondo',
  article: 'Artículo',
  paper: 'Paper / estudio',
  sector_report: 'Informe sectorial',
  personal_note: 'Nota personal',
  third_party_thesis: 'Tesis de terceros',
  own_thesis: 'Tesis propia',
  historical_case: 'Caso histórico',
  personal_postmortem: 'Postmortem personal',
};

function documentTypeLabel(value: string | null | undefined): string {
  if (!value) return NA;
  return DOCUMENT_TYPE_LABELS[value] ?? value.replaceAll('_', ' ');
}

/** Nombres internos del parser de ingesta (document_ingestion_service.py) en
 *  español: lo que importa es el formato del archivo, no la librería. */
const PARSER_LABELS: Record<string, string> = {
  native_text: 'Texto',
  native_html: 'HTML',
  pypdf: 'PDF',
  python_docx: 'Word',
  openpyxl: 'Excel',
};

function parserLabel(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'desconocido';
  const key = String(value);
  return PARSER_LABELS[key] ?? key.replaceAll('_', ' ');
}

/** Abre el explorador de un documento sin perder la página de la lista y
 *  saltando directamente a él (#fragmentos). */
function documentReaderHref(id: number, offset: number, q = ''): string {
  return `/knowledge?document=${id}${offset > 0 ? `&documentOffset=${offset}` : ''}${q ? `&q=${encodeURIComponent(q)}` : ''}#fragmentos`;
}

/** Vuelve a la lista de documentos en la misma página en la que se estaba. */
function libraryListHref(offset: number, q = ''): string {
  const params = new URLSearchParams({ ...(offset > 0 ? { documentOffset: String(offset) } : {}), ...(q ? { q } : {}) });
  return `/knowledge${params.size ? `?${params}` : ''}#documentos`;
}

function statusTone(status: string) {
  if (status === 'approved' || status === 'ready') return 'border-teal-800 text-teal-300';
  if (status === 'rejected') return 'border-red-900 text-red-300';
  return 'border-amber-900 text-amber-300';
}

export default async function KnowledgeLibraryPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const activeTab = asTab(query.tab);
  const documentId = Number(query.document);
  const selectedDocumentId = Number.isSafeInteger(documentId) && documentId > 0 ? documentId : null;
  const documentOffset = Number.isSafeInteger(Number(query.documentOffset)) && Number(query.documentOffset) >= 0 ? Number(query.documentOffset) : 0;
  const principleOffset = Number.isSafeInteger(Number(query.principleOffset)) && Number(query.principleOffset) >= 0 ? Number(query.principleOffset) : 0;
  const searchQuery = (query.q ?? '').trim().slice(0, 200);
  let library: Awaited<ReturnType<typeof getKnowledgeLibrary>>;
  try {
    library = await getKnowledgeLibrary({ documentOffset, principleOffset, status: query.status, q: searchQuery });
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature={t('knowledge.library')} retryHref="/knowledge" />;
    }
    throw error;
  }
  const { collections, documents, principles, jobs } = library;
  // Deep links resolve independently of the current page; 404 stays harmless.
  let selectedDocument: Awaited<ReturnType<typeof getKnowledgeDocument>> = null;
  if (selectedDocumentId !== null) {
    try {
      selectedDocument = await getKnowledgeDocument(selectedDocumentId);
    } catch (error) {
      if (isBackendUnavailableError(error)) return <BackendOffline feature={t('knowledge.library')} retryHref={`/knowledge?document=${selectedDocumentId}`} />;
      throw error;
    }
  }
  const selectedExists = selectedDocument !== null;
  let chunks: Awaited<ReturnType<typeof getKnowledgeDocumentChunks>> = [];
  if (selectedExists) {
    try {
      chunks = await getKnowledgeDocumentChunks(selectedDocument!.id);
    } catch (error) {
      if (isBackendUnavailableError(error)) {
        return <BackendOffline feature={t('knowledge.library')} retryHref={`/knowledge?document=${selectedDocumentId}`} />;
      }
      throw error;
    }
  }
  const visiblePrinciples = principles;
  const collectionNames = new Map(collections.map((collection) => [collection.id, collection.name]));
  const documentNames = new Map(documents.map((document) => [document.id, document.title]));
  const activeJobs = jobs.filter((job) => job.status === 'queued' || job.status === 'running');
  const collectionsWithCount = (() => {
    const withCount = collections.map((collection) => ({
      collection,
      count: library.collectionCounts[String(collection.id)] ?? 0,
    }));
    return {
      nonEmpty: withCount.filter((entry) => entry.count > 0),
      empty: withCount.filter((entry) => entry.count === 0),
    };
  })();
  const latestJobByDocument = new Map<number, (typeof jobs)[number]>();
  jobs.forEach((job) => {
    if (job.entity_id && !latestJobByDocument.has(job.entity_id)) {
      latestJobByDocument.set(job.entity_id, job);
    }
  });

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-6 overflow-x-clip md:pr-20">
      <ExtractionRefresh active={activeJobs.length > 0} />
      <PageHeader
        kicker="Conocimiento de inversión"
        title={t('knowledge.library')}
        description="Libros, cartas y casos de estudio, con principios aprobados a mano y trazables."
        actions={<div className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
          <LibraryChat scope="library" />
          <Button asChild className="h-11 w-full sm:w-auto" variant="outline"><Link href="/search"><FileSearch aria-hidden="true" className="h-4 w-4" />Buscar en todo</Link></Button>
          <Button asChild className="h-11 w-full sm:w-auto" variant="outline"><Link href="/knowledge-graph"><Library aria-hidden="true" className="h-4 w-4" />Grafo de conocimiento</Link></Button>
        </div>}
      />

      {/*
        Antes eran stats, jobs, dos formularios, tabla, explorador y curación de
        principios en un solo scroll de 8 secciones. Las pestañas separan las
        tres tareas (mirar la biblioteca / curar principios / subir) y el estado
        va en la URL, así que no hace falta JavaScript para cambiar de sección.
        `scroll={false}` en pestañas y filtros: cambiar de sección no devuelve
        al usuario al inicio de la página.
      */}
      <Tabs className="gap-4" value={activeTab}>
        <TabsList
          aria-label="Secciones de la biblioteca de conocimiento"
          className="flex h-auto w-full max-w-full snap-x gap-1 overflow-x-auto border border-gray-700 bg-gray-800 pb-2 text-gray-400 sm:inline-flex sm:h-9 sm:w-auto sm:overflow-visible sm:pb-[3px]"
          tabIndex={0}
        >
          {(['biblioteca', 'principios', 'subir'] as TabKey[]).map((key) => (
            <TabsTrigger
              asChild
              className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap"
              key={key}
              value={key}
            >
              <Link href={key === TABS.biblioteca ? '/knowledge' : `/knowledge?tab=${key}`} scroll={false}>{TAB_LABELS[key]}</Link>
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent className="mt-2 space-y-6" value={TABS.biblioteca}>
      {/*
        Lectura primero: al abrir un documento («Fragmentos» o su título) el
        explorador aparece arriba del todo (#fragmentos), no al final de la
        pestaña tras cifras, colecciones y la lista entera, donde el enlace
        parecía no hacer nada. La lista va antes que las colecciones; los
        formularios de alta viven en «Subir».
      */}
      {selectedDocument ? (
        <section aria-labelledby="fragmentos-titulo" className="min-w-0 scroll-mt-24 rounded-xl border border-teal-900/50 bg-surface-1 p-4 sm:p-5" id="fragmentos">
          <div className="mb-4 flex items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase text-teal-300">Explorador de fragmentos</p><h2 className="text-lg font-semibold text-gray-100" id="fragmentos-titulo">{selectedDocument.title}</h2></div><Button asChild className="h-11" size="sm" variant="outline"><Link href={libraryListHref(documentOffset, searchQuery)}>Volver a la lista</Link></Button></div>
          <ArchivedThesisNotice documentType={selectedDocument.document_type} />
          {/* Conexión 10a: asociar el documento a una empresa lo muestra en su ficha. Vacío = quitar. */}
          <MutationForm action={setKnowledgeDocumentTicker.bind(null, selectedDocument.id)} className="mb-4 flex flex-wrap items-end gap-2" successMessage="Ticker guardado">
            <div className="min-w-[12rem] flex-1 sm:flex-none">
              <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-doc-ticker">Empresa (ticker)</label>
              <Input autoCapitalize="characters" className="h-11 w-full uppercase" defaultValue={selectedDocument.ticker ?? ''} id="kw-doc-ticker" maxLength={32} name="ticker" placeholder="Sin empresa" />
            </div>
            <Button className="h-11" size="sm" type="submit" variant="outline">Guardar ticker</Button>
            {selectedDocument.ticker ? <Link className="pb-3 text-xs text-teal-300 hover:text-teal-200" href={`/research/${encodeURIComponent(selectedDocument.ticker)}?view=documents`}>Ver en la ficha de {selectedDocument.ticker}</Link> : null}
          </MutationForm>
          <div className="grid gap-3 md:max-h-[620px] md:overflow-y-auto md:pr-2">
            {chunks.map((chunk) => <article className="rounded-lg border border-gray-800 bg-black/30 p-4" key={chunk.id}><div className="mb-2 flex justify-between text-xs text-gray-500"><span>Fragmento {formatNumber(Number(chunk.chunk_index) + 1, { maximumFractionDigits: 0 })}</span><span>página {chunk.page_number === null || chunk.page_number === undefined ? NA : formatNumber(chunk.page_number, { maximumFractionDigits: 0 })} · {formatNumber(chunk.token_count, { maximumFractionDigits: 0 })} tokens</span></div><div className="text-sm leading-6 text-gray-300"><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{chunk.content}</ReactMarkdown></div></article>)}
            {!chunks.length ? <p className="text-sm text-gray-500">Este documento no tiene fragmentos.</p> : null}
          </div>
        </section>
      ) : null}
      {/* Tres cifras en una fila también en móvil: apiladas ocupaban ~300 px y
          empujaban el buscador y la lista fuera de la primera pantalla. */}
      <section aria-label="Resumen de la biblioteca" className="grid grid-cols-3 gap-2 sm:gap-4">
        {[
          ['Colecciones', collections.length],
          ['Documentos', library.documentTotal],
          ['Pendientes de aprobación', library.proposedTotal],
        ].map(([label, value]) => (
          <div className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-3 sm:p-4" key={label}>
            <div className="text-[11px] font-semibold uppercase leading-tight tracking-wide text-gray-500 sm:text-xs">{label}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-gray-100 sm:mt-2 sm:text-2xl">{formatNumber(Number(value), { maximumFractionDigits: 0 })}</div>
          </div>
        ))}
      </section>

      {activeJobs.length ? (
        <section className="rounded-xl border border-amber-900/60 bg-amber-950/10 p-4 text-sm text-amber-100">
          <div className="font-semibold">Extracción en segundo plano en curso</div><Link className="inline-flex min-h-11 items-center text-teal-300" href="/knowledge">Consultar estado</Link>
          <div className="mt-2 grid gap-1 text-amber-200/80">
            {activeJobs.map((job) => (
              <div key={job.id}>Tarea #{formatNumber(job.id, { maximumFractionDigits: 0 })} · {documentNames.get(job.entity_id ?? -1) ?? `documento ${job.entity_id}`} · {label(job.status)}{job.progress_total ? ` · lote ${formatNumber(job.progress_current, { maximumFractionDigits: 0 })}/${formatNumber(job.progress_total, { maximumFractionDigits: 0 })}` : ''}</div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="min-w-0 scroll-mt-24 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5" id="documentos">
        <div className="mb-4 flex items-center gap-2"><BookOpen aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="text-lg font-semibold text-gray-100">{t('knowledge.documents')}</h2></div>
        <LibrarySearchForm query={searchQuery} total={library.documentSearch?.total ?? null} />
        <PageNavigation offset={documentOffset} count={documents.length} total={library.documentSearch?.total ?? library.documentTotal} parameter="documentOffset" tab="biblioteca" q={searchQuery} />
        {!documents.length && !library.documentSearch ? <div className="py-2 text-sm text-gray-500"><p>No hay documentos en esta página.</p><Link className="mt-2 inline-flex min-h-[44px] items-center gap-2 rounded-md border border-teal-800 px-3 py-2 text-xs font-medium text-teal-300 hover:border-teal-600 hover:text-teal-200" href="/knowledge?tab=subir">Sube tu primer libro, carta o caso de estudio</Link></div> : null}
        <div aria-label="Documentos de conocimiento" className="hidden overflow-x-auto md:block" role="region" tabIndex={0}>
          <table className="w-full min-w-[560px] text-left text-sm">
            <caption className="sr-only">Documentos de conocimiento ingeridos, con colección, tipo, extractor, estado y acciones de extracción</caption>
            <thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2 pr-4" scope="col">Documento</th><th className="border-b border-gray-800 py-2 pr-4" scope="col">Colección</th><th className="border-b border-gray-800 py-2 pr-4" scope="col">Tipo</th><th className="border-b border-gray-800 py-2 pr-4" scope="col">Extractor</th><th className="border-b border-gray-800 py-2 pr-4" scope="col">Estado</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Acciones</th></tr></thead>
            <tbody>
              {documents.map((document) => {
                const job = latestJobByDocument.get(document.id);
                const busy = job?.status === 'queued' || job?.status === 'running';
                return (
                <tr className="border-b border-gray-900" key={document.id}>
                  <th className="py-3 pr-4 text-left text-sm font-normal" scope="row"><Link className="font-medium text-gray-200 hover:text-teal-200 hover:underline" href={documentReaderHref(document.id, documentOffset, searchQuery)}>{document.title}</Link><div className="text-xs text-gray-500">{document.author ?? 'Autor desconocido'}{document.publication_date && formatDate(document.publication_date, undefined, '') ? ` · ${formatDate(document.publication_date)}` : ''}</div>{document.ticker ? <Link className="mt-1 inline-block text-xs font-medium text-teal-300 hover:text-teal-200" href={`/research/${encodeURIComponent(document.ticker)}?view=documents`}>{document.ticker}</Link> : null}</th>
                  <td className="py-3 pr-4 text-gray-400">{document.collection_id ? collectionNames.get(document.collection_id) : 'Sin colección'}</td>
                  <td className="py-3 pr-4 text-gray-400">{documentTypeLabel(document.document_type)}</td>
                  <td className="py-3 pr-4 text-gray-500">{parserLabel(document.metadata.parser)}</td>
                  <td className="py-3 pr-4"><Badge className={statusTone(document.status)} variant="outline">{label(document.status)}</Badge></td>
                  <td className="py-3"><div className="flex flex-wrap justify-end gap-2"><Button asChild size="sm" variant="outline"><Link href={documentReaderHref(document.id, documentOffset, searchQuery)}>Fragmentos</Link></Button><MutationForm action={extractKnowledgePrinciples.bind(null, document.id)} successMessage="Extracción encolada"><Button disabled={busy} size="sm" type="submit"><Sparkles aria-hidden="true" className="h-4 w-4" />{busy ? label(job?.status) : 'Extraer'}</Button></MutationForm><DeleteDocumentButton documentId={document.id} title={document.title} /></div>{extractionResultText(job) ? <p className="mt-1 max-w-xs text-right text-xs text-gray-400" role="status">{extractionResultText(job)}</p> : null}</td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="grid grid-cols-1 gap-3 md:hidden">
          {documents.map((document) => {
            const job = latestJobByDocument.get(document.id);
            const busy = job?.status === 'queued' || job?.status === 'running';
            return (
              <article className="min-w-0 rounded-lg border border-gray-800 bg-black/30 p-4 break-words" key={document.id}>
                <Link className="block min-w-0 font-medium text-gray-200 hover:text-teal-200 hover:underline" href={documentReaderHref(document.id, documentOffset, searchQuery)}>{document.title}</Link>
                <div className="mt-1 text-xs text-gray-500">{document.author ?? 'Autor desconocido'}{document.publication_date && formatDate(document.publication_date, undefined, '') ? ` · ${formatDate(document.publication_date)}` : ''}</div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{document.collection_id ? collectionNames.get(document.collection_id) : 'Sin colección'}</Badge>
                  <Badge variant="outline">{documentTypeLabel(document.document_type)}</Badge>
                  <Badge className={statusTone(document.status)} variant="outline">{label(document.status)}</Badge>
                </div>
                <div className="mt-2 text-xs text-gray-500">Extractor: {parserLabel(document.metadata.parser)}</div>
                {extractionResultText(job) ? <p className="mt-2 text-xs text-gray-400" role="status">{extractionResultText(job)}</p> : null}
                <div className="mt-4 grid grid-cols-1 gap-2">
                  <Button asChild className="h-11 w-full" size="sm" variant="outline"><Link href={documentReaderHref(document.id, documentOffset, searchQuery)}>Fragmentos</Link></Button>
                  <MutationForm action={extractKnowledgePrinciples.bind(null, document.id)} successMessage="Extracción encolada">
                    <Button className="h-11 w-full" disabled={busy} size="sm" type="submit"><Sparkles aria-hidden="true" className="h-4 w-4" />{busy ? label(job?.status) : 'Extraer'}</Button>
                  </MutationForm>
                  <DeleteDocumentButton className="h-11 w-full" documentId={document.id} title={document.title} />
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <PageNavigation offset={documentOffset} count={documents.length} total={library.documentSearch?.total ?? library.documentTotal} parameter="documentOffset" tab="biblioteca" q={searchQuery} />

      <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
        <h2 className="mb-3 font-semibold text-gray-100">Colecciones</h2>
        {/*
          Las vacías (p. ej. las 10 instaladas por defecto antes de subir
          nada) no compiten con las que tienen documentos: quedan plegadas
          bajo un desplegable, donde sigue estando su botón de borrado.
        */}
        {collections.length ? (
          <>
            {collectionsWithCount.nonEmpty.length ? (
              <ul className="grid gap-2 sm:grid-cols-2">
                {collectionsWithCount.nonEmpty.map(({ collection, count }) => (
                  <li className="flex items-center justify-between gap-2 rounded-lg border border-gray-800 p-3 text-sm" key={collection.id}>
                    <span>
                      <span className="font-medium text-gray-200">{collection.name}</span>
                      <span className="ml-2 text-xs text-gray-500">· {count} {count === 1 ? 'documento' : 'documentos'}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-gray-500">Ninguna colección tiene documentos todavía.</p>}
            {collectionsWithCount.empty.length ? (
              <details className="mt-3">
                <summary className="inline-flex min-h-[44px] cursor-pointer items-center text-sm text-gray-500">
                  {collectionsWithCount.empty.length} {collectionsWithCount.empty.length === 1 ? 'colección vacía' : 'colecciones vacías'}
                </summary>
                <ul className="grid gap-2 sm:grid-cols-2">
                  {collectionsWithCount.empty.map(({ collection }) => (
                    <li className="flex items-center justify-between gap-2 rounded-lg border border-gray-800 p-3 text-sm" key={collection.id}>
                      <span className="font-medium text-gray-200">{collection.name}</span>
                      <DeleteCollectionButton collectionId={collection.id} name={collection.name} />
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </>
        ) : <p className="text-sm text-gray-500">Sin colecciones.</p>}
      </section>
        </TabsContent>

        <TabsContent className="mt-2" value={TABS.subir}>
          <MutationForm id="upload-knowledge" action={uploadKnowledgeDocumentResult} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Documento ingerido">
            <div className="mb-4 flex items-center gap-2"><UploadCloud aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">{t('knowledge.upload')}</h2></div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {/* F142: etiquetas visibles - antes solo había placeholders/valores
                  de ejemplo y campos sin nombre («Date», «book», «en»). */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-title">Título</label>
                <Input className="h-11 w-full" id="kw-title" name="title" placeholder="Título del documento" required />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-collection">Colección</label>
                <select className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" id="kw-collection" name="collection_id" defaultValue="">
                  <option value="">Sin colección</option>
                  {collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-author">Autor</label>
                <Input className="h-11 w-full" id="kw-author" name="author" placeholder="Autor" />
              </div>
              {/* Conexión 10a: el ticker opcional enlaza el documento con la
                  ficha de la empresa (vista Documentos de /research/[ticker]). */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-ticker">Ticker de la empresa (opcional)</label>
                <Input autoCapitalize="characters" className="h-11 w-full uppercase" id="kw-ticker" maxLength={32} name="ticker" placeholder="p. ej. UBER o SAN.MC" />
              </div>
              {/* F142: tipo como textbox libre con «book» no decía qué vocabulario
                  acepta el backend. Select con los 9 tipos de
                  KNOWLEDGE_DOCUMENT_TYPES, etiquetados en español. */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-doctype">Tipo de documento</label>
                <select className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" id="kw-doctype" name="document_type" defaultValue="book" required>
                  <option value="book">Libro</option>
                  <option value="fund_letter">Carta de fondo</option>
                  <option value="article">Artículo</option>
                  <option value="paper">Paper / estudio</option>
                  <option value="sector_report">Informe sectorial</option>
                  <option value="personal_note">Nota personal</option>
                  <option value="third_party_thesis">Tesis de terceros</option>
                  <option value="own_thesis">Tesis propia</option>
                  <option value="historical_case">Caso histórico</option>
                  <option value="personal_postmortem">Postmortem personal</option>
                </select>
              </div>
              {/* F142: la fecha es un input date nativo - su formato (dd/mm o
                  mm/dd) lo fija el idioma del navegador del usuario, no la app;
                  la etiqueta deja claro qué se pide. */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-pubdate">Fecha de publicación</label>
                <Input className="h-11 w-full" id="kw-pubdate" name="publication_date" type="date" />
              </div>
              {/* F142: el backend solo acepta «es» o «en» (validación en
                  knowledge.py) - select en vez de texto libre. «en» por
                  defecto: la mayoría de la biblioteca son cartas de fondo en
                  inglés (dato prod: 48 en / 26 es). */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-language">Idioma del documento</label>
                <select className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" id="kw-language" name="language" defaultValue="en" required>
                  <option value="en">Inglés</option>
                  <option value="es">Español</option>
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-source-url">URL de la fuente (opcional)</label>
                <Input className="h-11 w-full" id="kw-source-url" name="source_url" placeholder="https://…" type="url" />
              </div>
              <div className="sm:col-span-2">
                <span className="mb-1 block text-xs font-medium text-gray-400">Archivo</span>
                {/* F287: sin h-11 - FileUploadInput es un compuesto (fila del boton
                Elegir archivo + pista "Maximo N MB.") de ~70px; fijar 44px
                hacia que la pista desbordara la caja y el boton Subir de la
                siguiente fila del grid la solapara 8px en movil. */}
                <FileUploadInput accept=".pdf,.docx,.txt,.md,.html,.xlsx,.csv" className="w-full" name="file" required />
              </div>
              <Button className="h-11 w-full sm:col-span-2 sm:w-fit" type="submit"><UploadCloud aria-hidden="true" className="h-4 w-4" />Subir</Button>
            </div>
          </MutationForm>
          <section className="mt-6 grid grid-cols-1 gap-4 sm:gap-6 xl:grid-cols-2">
            <MutationForm action={createKnowledgeCollectionResult} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Colección creada">
              <div className="mb-4 flex items-center gap-2"><Library aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">Nueva colección</h2></div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Nombre de la colección</span><Input className="h-11 w-full" name="name" placeholder={t('knowledge.qualityCompounders')} required /></label>
                <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Tipo de colección</span><select className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" name="collection_type" defaultValue="custom" required><option value="custom">Personalizada</option><option value="investor">Por inversor o autor</option><option value="theme">Por tema o sector</option></select></label>
                <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 sm:col-span-2"><span>Descripción (opcional)</span><Textarea className="min-h-[88px] w-full" name="description" placeholder="Ámbito y uso previsto" /></label>
                <Button className="h-11 w-full sm:col-span-2 sm:w-fit" type="submit">Crear colección</Button>
              </div>
            </MutationForm>

            <div className="rounded-xl border border-gray-800 bg-surface-1 p-5">
              <div className="mb-4 flex items-center gap-2"><Library aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">Colecciones por defecto</h2></div>
              {hasDefaultCollections(collections) ? <p className="text-sm text-gray-400">Colecciones por defecto instaladas.</p> : <MutationForm action={installKnowledgeDefaults} successMessage="Colecciones por defecto listas">
                <Button className="h-11 w-full sm:w-fit" type="submit"><Library aria-hidden="true" className="h-4 w-4" />Instalar por defecto</Button>
              </MutationForm>}
            </div>
          </section>
        </TabsContent>

        <TabsContent className="mt-2" value={TABS.principios}>
      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center"><div className="flex items-center gap-2"><Sparkles aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="text-lg font-semibold text-gray-100">Principios de inversión</h2></div><div className="flex flex-wrap gap-2 md:ml-auto">{['', 'proposed', 'approved', 'rejected', 'merged', 'superseded'].map((status) => <Button asChild className="min-h-[44px]" key={status || 'all'} size="sm" variant={(query.status ?? '') === status ? 'default' : 'outline'}><Link href={status ? `/knowledge?tab=principios&status=${status}` : '/knowledge?tab=principios'} scroll={false}>{PRINCIPLE_STATUS_LABELS[status] ?? status}</Link></Button>)}</div></div>
        <PageNavigation offset={principleOffset} count={principles.length} total={library.principleTotal} parameter="principleOffset" tab="principios" status={query.status} />
        <div className="grid gap-4 xl:grid-cols-2">
          {visiblePrinciples.map((principle) => (
            <article className="min-w-0 rounded-lg border border-gray-800 bg-black/30 p-4 break-words" key={principle.id}>
              <div className="flex flex-wrap items-center gap-2"><Badge variant="outline" className={statusTone(principle.status)}>{label(principle.status)}</Badge><Badge variant="outline">{principle.category}</Badge><span className="text-xs text-gray-500">v{formatNumber(Number(principle.version), { maximumFractionDigits: 0 })} · confianza {formatPercent(Number(principle.confidence), { digits: 0 })}</span></div>
              <h3 className="mt-3 font-semibold leading-6 text-gray-100">{principle.principle}</h3>
              <blockquote className="mt-3 border-l-2 border-teal-900 pl-3 text-sm italic leading-6 text-gray-400">{principle.exact_fragment}</blockquote>
              <div className="mt-3 text-xs text-gray-500">{documentNames.get(principle.knowledge_document_id) ?? `Documento #${principle.knowledge_document_id}`} · página {principle.page_number === null || principle.page_number === undefined ? NA : formatNumber(principle.page_number, { maximumFractionDigits: 0 })}</div>
              {principle.application_conditions.length ? <p className="mt-3 text-sm text-gray-300"><span className="font-semibold text-gray-400">Aplicar cuando:</span> {principle.application_conditions.join('; ')}</p> : null}
              {principle.exceptions.length ? <p className="mt-2 text-sm text-amber-200"><span className="font-semibold">Excepciones:</span> {principle.exceptions.join('; ')}</p> : null}
              {principle.semantic_duplicate_of_id ? <div className="mt-3 rounded border border-amber-900/60 bg-amber-950/20 p-2 text-xs text-amber-200">Posible duplicado del principio #{principle.semantic_duplicate_of_id}. Revísalo antes de aprobar.</div> : null}
              {principle.status === 'proposed' ? <div className="mt-4 flex flex-wrap gap-2"><MutationForm action={decideKnowledgePrinciple.bind(null, principle.id, 'approve')} successMessage="Principio aprobado"><Button className="min-h-[44px]" size="sm" type="submit"><Check aria-hidden="true" className="h-4 w-4" />Aprobar</Button></MutationForm><MutationForm action={decideKnowledgePrinciple.bind(null, principle.id, 'reject')} successMessage="Principio rechazado"><Button className="min-h-[44px]" size="sm" type="submit" variant="outline"><X aria-hidden="true" className="h-4 w-4" />Rechazar</Button></MutationForm>{principle.semantic_duplicate_of_id ? <MutationForm action={mergeKnowledgePrinciple.bind(null, principle.id, principle.semantic_duplicate_of_id)} successMessage="Principio fusionado"><Button className="min-h-[44px]" size="sm" type="submit" variant="outline">Fusionar duplicado</Button></MutationForm> : null}</div> : null}
              {['proposed', 'approved'].includes(principle.status) ? <details className="mt-4 border-t border-gray-800 pt-3"><summary className="cursor-pointer text-xs font-semibold uppercase text-gray-500">Corregir como nueva versión</summary><MutationForm action={reviseKnowledgePrincipleResult.bind(null, principle.id)} className="mt-3 grid grid-cols-1 gap-2" successMessage="Revisión propuesta"><Textarea className="min-h-[88px] w-full text-base md:text-sm" defaultValue={principle.principle} name="principle" required /><Input className="h-11 w-full" defaultValue={principle.category} name="category" required /><Input className="h-11 w-full" defaultValue={principle.application_conditions.join(', ')} name="application_conditions" placeholder="Condiciones, separadas por comas" /><Input className="h-11 w-full" defaultValue={principle.exceptions.join(', ')} name="exceptions" placeholder="Excepciones, separadas por comas" /><Button className="h-11 w-full sm:w-fit" size="sm" type="submit">Crear revisión</Button></MutationForm></details> : null}
            </article>
          ))}
          {!visiblePrinciples.length ? (
            library.principleTotal > 0 || query.status ? (
              <p className="text-sm text-gray-500">
                Ningún principio coincide con este filtro.{' '}
                <Link className="text-teal-300 underline underline-offset-2" href="/knowledge?tab=principios">Ver todos</Link>
              </p>
            ) : (
              <div className="rounded-lg border border-dashed border-gray-800 p-4">
                <p className="text-sm text-gray-400">
                  {activeJobs.length
                    ? 'Extracción en curso: los principios aparecen aquí al terminar.'
                    : noPrinciplesText(jobs)}
                </p>
                {!activeJobs.length ? (
                  <Button asChild className="mt-3 min-h-[44px]" size="sm" variant="outline">
                    <Link href="/knowledge">Ir a la Biblioteca</Link>
                  </Button>
                ) : null}
              </div>
            )
          ) : null}
        </div>
        <PageNavigation offset={principleOffset} count={principles.length} total={library.principleTotal} parameter="principleOffset" tab="principios" status={query.status} />
      </section>
        </TabsContent>
      </Tabs>
    </main>
  );
}

function PageNavigation({ offset, count, total, parameter, tab, status, q }: {
  offset: number; count: number; total: number; parameter: string; tab: string; status?: string; q?: string;
}) {
  const href = (next: number) => `/knowledge?${new URLSearchParams({ tab, [parameter]: String(next), ...(status ? { status } : {}), ...(q ? { q } : {}) })}`;
  if (offset === 0 && offset + count >= total) return null;
  return <nav aria-label={tab === 'principios' ? 'Páginas de principios' : 'Páginas de documentos'} className="my-4 flex flex-wrap items-center gap-3 text-sm text-gray-400">
    <span>{count ? `${offset + 1}-${offset + count} de ${total}` : `0 de ${total}`}</span>
    {offset > 0 ? <Button asChild variant="outline" className="min-h-11"><Link href={href(Math.max(0, offset - KNOWLEDGE_PAGE_SIZE))}>Anteriores</Link></Button> : null}
    {offset + count < total ? <Button asChild variant="outline" className="min-h-11"><Link href={href(offset + KNOWLEDGE_PAGE_SIZE)}>Siguientes</Link></Button> : null}
  </nav>;
}
