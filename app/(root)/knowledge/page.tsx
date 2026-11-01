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
import { formatDate, formatNumber, formatPercent } from '@/lib/format';
import { getLocale, getT } from '@/lib/i18n/server';
import type { TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('knowledge.metadataTitle'), description: t('knowledge.metadataDescription') };
}

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

const TAB_LABELS: Record<TabKey, TranslationKey> = {
  biblioteca: 'knowledge.tabs.biblioteca',
  principios: 'knowledge.tabs.principios',
  subir: 'knowledge.tabs.subir',
};

function asTab(value: string | undefined): TabKey {
  return value === TABS.principios || value === TABS.subir ? value : TABS.biblioteca;
}

const PRINCIPLE_STATUS_LABELS: Record<string, TranslationKey> = {
  '': 'knowledge.principleStatus.all',
  proposed: 'knowledge.principleStatus.proposed',
  approved: 'knowledge.principleStatus.approved',
  rejected: 'knowledge.principleStatus.rejected',
  merged: 'knowledge.principleStatus.merged',
  superseded: 'knowledge.principleStatus.superseded',
};

/** Claves de diccionario para los estados persistidos por el backend */
const STATUS_LABELS: Record<string, TranslationKey> = {
  queued: 'knowledge.status.queued',
  running: 'knowledge.status.running',
  succeeded: 'knowledge.status.succeeded',
  failed: 'knowledge.status.failed',
  pending: 'knowledge.status.pending',
  processing: 'knowledge.status.processing',
  ready: 'knowledge.status.ready',
  proposed: 'knowledge.status.proposed',
  approved: 'knowledge.status.approved',
  rejected: 'knowledge.status.rejected',
  merged: 'knowledge.status.merged',
  superseded: 'knowledge.status.superseded',
};

function label(value: string | null | undefined, t: TranslateFn): string {
  if (!value) return t('common.na');
  return Object.hasOwn(STATUS_LABELS, value) ? t(STATUS_LABELS[value]) : value.replaceAll('_', ' ');
}

/** Mismo vocabulario que el select de subida (KNOWLEDGE_DOCUMENT_TYPES del
 *  backend): la tabla y las tarjetas pintan la etiqueta, no la clave. */
const DOCUMENT_TYPE_LABELS: Record<string, TranslationKey> = {
  book: 'knowledge.documentTypes.book',
  fund_letter: 'knowledge.documentTypes.fundLetter',
  article: 'knowledge.documentTypes.article',
  paper: 'knowledge.documentTypes.paper',
  sector_report: 'knowledge.documentTypes.sectorReport',
  personal_note: 'knowledge.documentTypes.personalNote',
  third_party_thesis: 'knowledge.documentTypes.thirdPartyThesis',
  own_thesis: 'knowledge.documentTypes.ownThesis',
  historical_case: 'knowledge.documentTypes.historicalCase',
  personal_postmortem: 'knowledge.documentTypes.personalPostmortem',
};

function documentTypeLabel(value: string | null | undefined, t: TranslateFn): string {
  if (!value) return t('common.na');
  return Object.hasOwn(DOCUMENT_TYPE_LABELS, value) ? t(DOCUMENT_TYPE_LABELS[value]) : value.replaceAll('_', ' ');
}

/** Nombres internos del parser de ingesta (document_ingestion_service.py) en
 *  español: lo que importa es el formato del archivo, no la librería. */
const PARSER_LABELS: Record<string, TranslationKey> = {
  native_text: 'knowledge.parsers.nativeText',
  native_html: 'knowledge.parsers.nativeHtml',
  pypdf: 'knowledge.parsers.pypdf',
  python_docx: 'knowledge.parsers.pythonDocx',
  openpyxl: 'knowledge.parsers.openpyxl',
};

function parserLabel(value: unknown, t: TranslateFn): string {
  if (value === null || value === undefined || value === '') return t('knowledge.parserUnknown');
  const key = String(value);
  return Object.hasOwn(PARSER_LABELS, key) ? t(PARSER_LABELS[key]) : key.replaceAll('_', ' ');
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
  const t = await getT();
  const locale = await getLocale();
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
        kicker={t('knowledge.kicker')}
        title={t('knowledge.library')}
        description={t('knowledge.description')}
        actions={<div className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
          <LibraryChat scope="library" />
          <Button asChild className="h-11 w-full sm:w-auto" variant="outline"><Link href="/search"><FileSearch aria-hidden="true" className="h-4 w-4" />{t('knowledge.searchAll')}</Link></Button>
          <Button asChild className="h-11 w-full sm:w-auto" variant="outline"><Link href="/knowledge-graph"><Library aria-hidden="true" className="h-4 w-4" />{t('knowledgeGraph.canvas.feature')}</Link></Button>
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
          aria-label={t('knowledge.tabsAria')}
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
              <Link href={key === TABS.biblioteca ? '/knowledge' : `/knowledge?tab=${key}`} scroll={false}>{t(TAB_LABELS[key])}</Link>
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
          <div className="mb-4 flex items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase text-teal-300">{t('knowledge.explorerTitle')}</p><h2 className="text-lg font-semibold text-gray-100" id="fragmentos-titulo">{selectedDocument.title}</h2></div><Button asChild className="h-11" size="sm" variant="outline"><Link href={libraryListHref(documentOffset, searchQuery)}>{t('knowledge.backToList')}</Link></Button></div>
          <ArchivedThesisNotice documentType={selectedDocument.document_type} t={t} />
          {/* Conexión 10a: asociar el documento a una empresa lo muestra en su ficha. Vacío = quitar. */}
          <MutationForm action={setKnowledgeDocumentTicker.bind(null, selectedDocument.id)} className="mb-4 flex flex-wrap items-end gap-2" successMessage={t('knowledge.tickerSaved')}>
            <div className="min-w-[12rem] flex-1 sm:flex-none">
              <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-doc-ticker">{t('knowledge.tickerLabel')}</label>
              <Input autoCapitalize="characters" className="h-11 w-full uppercase" defaultValue={selectedDocument.ticker ?? ''} id="kw-doc-ticker" maxLength={32} name="ticker" placeholder={t('knowledge.tickerPlaceholder')} />
            </div>
            <Button className="h-11" size="sm" type="submit" variant="outline">{t('knowledge.tickerSave')}</Button>
            {selectedDocument.ticker ? <Link className="pb-3 text-xs text-teal-300 hover:text-teal-200" href={`/research/${encodeURIComponent(selectedDocument.ticker)}?view=documents`}>{t('knowledge.viewInProfile', { ticker: selectedDocument.ticker })}</Link> : null}
          </MutationForm>
          <div className="grid gap-3 md:max-h-[620px] md:overflow-y-auto md:pr-2">
            {chunks.map((chunk) => <article className="rounded-lg border border-gray-800 bg-black/30 p-4" key={chunk.id}><div className="mb-2 flex justify-between text-xs text-gray-500"><span>{t('knowledge.chunk', { n: formatNumber(Number(chunk.chunk_index) + 1, { maximumFractionDigits: 0 }, undefined, locale) })}</span><span>{t('knowledge.pageTokens', { page: chunk.page_number === null || chunk.page_number === undefined ? t('common.na') : formatNumber(chunk.page_number, { maximumFractionDigits: 0 }, undefined, locale), tokens: formatNumber(chunk.token_count, { maximumFractionDigits: 0 }, undefined, locale) })}</span></div><div className="text-sm leading-6 text-gray-300"><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{chunk.content}</ReactMarkdown></div></article>)}
            {!chunks.length ? <p className="text-sm text-gray-500">{t('knowledge.noChunks')}</p> : null}
          </div>
        </section>
      ) : null}
      {/* Tres cifras en una fila también en móvil: apiladas ocupaban ~300 px y
          empujaban el buscador y la lista fuera de la primera pantalla. */}
      <section aria-label={t('knowledge.statsAria')} className="grid grid-cols-3 gap-2 sm:gap-4">
        {[
          [t('knowledge.stats.collections'), collections.length],
          [t('knowledge.stats.documents'), library.documentTotal],
          [t('knowledge.stats.pendingApproval'), library.proposedTotal],
        ].map(([label, value]) => (
          <div className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-3 sm:p-4" key={label}>
            <div className="text-[11px] font-semibold uppercase leading-tight tracking-wide text-gray-500 sm:text-xs">{label}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-gray-100 sm:mt-2 sm:text-2xl">{formatNumber(Number(value), { maximumFractionDigits: 0 }, undefined, locale)}</div>
          </div>
        ))}
      </section>

      {activeJobs.length ? (
        <section className="rounded-xl border border-amber-900/60 bg-amber-950/10 p-4 text-sm text-amber-100">
          <div className="font-semibold">{t('knowledge.jobsTitle')}</div><Link className="inline-flex min-h-11 items-center text-teal-300" href="/knowledge">{t('knowledge.jobsCheckStatus')}</Link>
          <div className="mt-2 grid gap-1 text-amber-200/80">
            {activeJobs.map((job) => (
              <div key={job.id}>{t('knowledge.jobTask', { id: formatNumber(job.id, { maximumFractionDigits: 0 }, undefined, locale) })} · {documentNames.get(job.entity_id ?? -1) ?? t('knowledge.jobDocument', { id: String(job.entity_id) })} · {label(job.status, t)}{job.progress_total ? ` · ${t('knowledge.jobBatch', { current: formatNumber(job.progress_current, { maximumFractionDigits: 0 }, undefined, locale), total: formatNumber(job.progress_total, { maximumFractionDigits: 0 }, undefined, locale) })}` : ''}</div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="min-w-0 scroll-mt-24 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5" id="documentos">
        <div className="mb-4 flex items-center gap-2"><BookOpen aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="text-lg font-semibold text-gray-100">{t('knowledge.documents')}</h2></div>
        <LibrarySearchForm locale={locale} query={searchQuery} t={t} total={library.documentSearch?.total ?? null} />
        <PageNavigation offset={documentOffset} count={documents.length} total={library.documentSearch?.total ?? library.documentTotal} parameter="documentOffset" tab="biblioteca" q={searchQuery} t={t} />
        {!documents.length && !library.documentSearch ? <div className="py-2 text-sm text-gray-500"><p>{t('knowledge.emptyDocuments')}</p><Link className="mt-2 inline-flex min-h-[44px] items-center gap-2 rounded-md border border-teal-800 px-3 py-2 text-xs font-medium text-teal-300 hover:border-teal-600 hover:text-teal-200" href="/knowledge?tab=subir">{t('knowledge.uploadFirst')}</Link></div> : null}
        <div aria-label={t('knowledge.documentsAria')} className="hidden overflow-x-auto md:block" role="region" tabIndex={0}>
          <table className="w-full min-w-[560px] text-left text-sm">
            <caption className="sr-only">{t('knowledge.tableCaption')}</caption>
            <thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2 pr-4" scope="col">{t('knowledge.colDocument')}</th><th className="border-b border-gray-800 py-2 pr-4" scope="col">{t('knowledge.colCollection')}</th><th className="border-b border-gray-800 py-2 pr-4" scope="col">{t('knowledge.colType')}</th><th className="border-b border-gray-800 py-2 pr-4" scope="col">{t('knowledge.colParser')}</th><th className="border-b border-gray-800 py-2 pr-4" scope="col">{t('knowledge.colStatus')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{t('knowledge.colActions')}</th></tr></thead>
            <tbody>
              {documents.map((document) => {
                const job = latestJobByDocument.get(document.id);
                const busy = job?.status === 'queued' || job?.status === 'running';
                return (
                <tr className="border-b border-gray-900" key={document.id}>
                  <th className="py-3 pr-4 text-left text-sm font-normal" scope="row"><Link className="font-medium text-gray-200 hover:text-teal-200 hover:underline" href={documentReaderHref(document.id, documentOffset, searchQuery)}>{document.title}</Link><div className="text-xs text-gray-500">{document.author ?? t('knowledge.unknownAuthor')}{document.publication_date && formatDate(document.publication_date, undefined, '') ? ` · ${formatDate(document.publication_date, undefined, undefined, locale)}` : ''}</div>{document.ticker ? <Link className="mt-1 inline-block text-xs font-medium text-teal-300 hover:text-teal-200" href={`/research/${encodeURIComponent(document.ticker)}?view=documents`}>{document.ticker}</Link> : null}</th>
                  <td className="py-3 pr-4 text-gray-400">{document.collection_id ? collectionNames.get(document.collection_id) : t('knowledge.noCollection')}</td>
                  <td className="py-3 pr-4 text-gray-400">{documentTypeLabel(document.document_type, t)}</td>
                  <td className="py-3 pr-4 text-gray-500">{parserLabel(document.metadata.parser, t)}</td>
                  <td className="py-3 pr-4"><Badge className={statusTone(document.status)} variant="outline">{label(document.status, t)}</Badge></td>
                  <td className="py-3"><div className="flex flex-wrap justify-end gap-2"><Button asChild size="sm" variant="outline"><Link href={documentReaderHref(document.id, documentOffset, searchQuery)}>{t('knowledge.fragments')}</Link></Button><MutationForm action={extractKnowledgePrinciples.bind(null, document.id)} successMessage={t('knowledge.extractQueued')}><Button disabled={busy} size="sm" type="submit"><Sparkles aria-hidden="true" className="h-4 w-4" />{busy ? label(job?.status, t) : t('knowledge.extract')}</Button></MutationForm><DeleteDocumentButton documentId={document.id} title={document.title} /></div>{extractionResultText(job, t) ? <p className="mt-1 max-w-xs text-right text-xs text-gray-400" role="status">{extractionResultText(job, t)}</p> : null}</td>
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
                <Link className="flex min-h-[44px] min-w-0 items-center font-medium text-gray-200 hover:text-teal-200 hover:underline" href={documentReaderHref(document.id, documentOffset, searchQuery)}>{document.title}</Link>
                <div className="mt-1 text-xs text-gray-500">{document.author ?? t('knowledge.unknownAuthor')}{document.publication_date && formatDate(document.publication_date, undefined, '') ? ` · ${formatDate(document.publication_date, undefined, undefined, locale)}` : ''}</div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{document.collection_id ? collectionNames.get(document.collection_id) : t('knowledge.noCollection')}</Badge>
                  <Badge variant="outline">{documentTypeLabel(document.document_type, t)}</Badge>
                  <Badge className={statusTone(document.status)} variant="outline">{label(document.status, t)}</Badge>
                </div>
                <div className="mt-2 text-xs text-gray-500">{t('knowledge.parserLine', { parser: parserLabel(document.metadata.parser, t) })}</div>
                {extractionResultText(job, t) ? <p className="mt-2 text-xs text-gray-400" role="status">{extractionResultText(job, t)}</p> : null}
                <div className="mt-4 grid grid-cols-1 gap-2">
                  <Button asChild className="h-11 w-full" size="sm" variant="outline"><Link href={documentReaderHref(document.id, documentOffset, searchQuery)}>{t('knowledge.fragments')}</Link></Button>
                  <MutationForm action={extractKnowledgePrinciples.bind(null, document.id)} successMessage={t('knowledge.extractQueued')}>
                    <Button className="h-11 w-full" disabled={busy} size="sm" type="submit"><Sparkles aria-hidden="true" className="h-4 w-4" />{busy ? label(job?.status, t) : t('knowledge.extract')}</Button>
                  </MutationForm>
                  <DeleteDocumentButton className="h-11 w-full" documentId={document.id} title={document.title} />
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <PageNavigation offset={documentOffset} count={documents.length} total={library.documentSearch?.total ?? library.documentTotal} parameter="documentOffset" tab="biblioteca" q={searchQuery} t={t} />

      <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
        <h2 className="mb-3 font-semibold text-gray-100">{t('knowledge.stats.collections')}</h2>
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
                      <span className="ml-2 text-xs text-gray-500">· {count === 1 ? t('knowledge.documentsCount.one', { count }) : t('knowledge.documentsCount.other', { count })}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-gray-500">{t('knowledge.noCollectionsWithDocs')}</p>}
            {collectionsWithCount.empty.length ? (
              <details className="mt-3">
                <summary className="inline-flex min-h-[44px] cursor-pointer items-center text-sm text-gray-500">
                  {collectionsWithCount.empty.length === 1 ? t('knowledge.emptyCollections.one', { count: collectionsWithCount.empty.length }) : t('knowledge.emptyCollections.other', { count: collectionsWithCount.empty.length })}
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
        ) : <p className="text-sm text-gray-500">{t('knowledge.noCollections')}</p>}
      </section>
        </TabsContent>

        <TabsContent className="mt-2" value={TABS.subir}>
          <MutationForm id="upload-knowledge" action={uploadKnowledgeDocumentResult} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage={t('knowledge.uploadSuccess')}>
            <div className="mb-4 flex items-center gap-2"><UploadCloud aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">{t('knowledge.upload')}</h2></div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {/* F142: etiquetas visibles - antes solo había placeholders/valores
                  de ejemplo y campos sin nombre («Date», «book», «en»). */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-title">{t('knowledge.titleLabel')}</label>
                <Input className="h-11 w-full" id="kw-title" name="title" placeholder={t('knowledge.titlePlaceholder')} required />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-collection">{t('knowledge.colCollection')}</label>
                <select className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" id="kw-collection" name="collection_id" defaultValue="">
                  <option value="">{t('knowledge.noCollection')}</option>
                  {collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-author">{t('knowledge.authorLabel')}</label>
                <Input className="h-11 w-full" id="kw-author" name="author" placeholder={t('knowledge.authorLabel')} />
              </div>
              {/* Conexión 10a: el ticker opcional enlaza el documento con la
                  ficha de la empresa (vista Documentos de /research/[ticker]). */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-ticker">{t('knowledge.tickerOptionalLabel')}</label>
                <Input autoCapitalize="characters" className="h-11 w-full uppercase" id="kw-ticker" maxLength={32} name="ticker" placeholder={t('knowledge.tickerExamplePlaceholder')} />
              </div>
              {/* F142: tipo como textbox libre con «book» no decía qué vocabulario
                  acepta el backend. Select con los 9 tipos de
                  KNOWLEDGE_DOCUMENT_TYPES, etiquetados en español. */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-doctype">{t('knowledge.typeLabel')}</label>
                <select className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" id="kw-doctype" name="document_type" defaultValue="book" required>
                  <option value="book">{t('knowledge.documentTypes.book')}</option>
                  <option value="fund_letter">{t('knowledge.documentTypes.fundLetter')}</option>
                  <option value="article">{t('knowledge.documentTypes.article')}</option>
                  <option value="paper">{t('knowledge.documentTypes.paper')}</option>
                  <option value="sector_report">{t('knowledge.documentTypes.sectorReport')}</option>
                  <option value="personal_note">{t('knowledge.documentTypes.personalNote')}</option>
                  <option value="third_party_thesis">{t('knowledge.documentTypes.thirdPartyThesis')}</option>
                  <option value="own_thesis">{t('knowledge.documentTypes.ownThesis')}</option>
                  <option value="historical_case">{t('knowledge.documentTypes.historicalCase')}</option>
                  <option value="personal_postmortem">{t('knowledge.documentTypes.personalPostmortem')}</option>
                </select>
              </div>
              {/* F142: la fecha es un input date nativo - su formato (dd/mm o
                  mm/dd) lo fija el idioma del navegador del usuario, no la app;
                  la etiqueta deja claro qué se pide. */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-pubdate">{t('knowledge.publicationDateLabel')}</label>
                <Input className="h-11 w-full" id="kw-pubdate" name="publication_date" type="date" />
              </div>
              {/* F142: el backend solo acepta «es» o «en» (validación en
                  knowledge.py) - select en vez de texto libre. «en» por
                  defecto: la mayoría de la biblioteca son cartas de fondo en
                  inglés (dato prod: 48 en / 26 es). */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-language">{t('knowledge.languageLabel')}</label>
                <select className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" id="kw-language" name="language" defaultValue="en" required>
                  <option value="en">{t('knowledge.languageEn')}</option>
                  <option value="es">{t('knowledge.languageEs')}</option>
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-source-url">{t('knowledge.sourceUrlLabel')}</label>
                <Input className="h-11 w-full" id="kw-source-url" name="source_url" placeholder="https://…" type="url" />
              </div>
              <div className="sm:col-span-2">
                <span className="mb-1 block text-xs font-medium text-gray-400">{t('knowledge.fileLabel')}</span>
                {/* F287: sin h-11 - FileUploadInput es un compuesto (fila del boton
                Elegir archivo + pista "Maximo N MB.") de ~70px; fijar 44px
                hacia que la pista desbordara la caja y el boton Subir de la
                siguiente fila del grid la solapara 8px en movil. */}
                <FileUploadInput accept=".pdf,.docx,.txt,.md,.html,.xlsx,.csv" className="w-full" name="file" required />
              </div>
              <Button className="h-11 w-full sm:col-span-2 sm:w-fit" type="submit"><UploadCloud aria-hidden="true" className="h-4 w-4" />{t('knowledge.uploadAction')}</Button>
            </div>
          </MutationForm>
          <section className="mt-6 grid grid-cols-1 gap-4 sm:gap-6 xl:grid-cols-2">
            <MutationForm action={createKnowledgeCollectionResult} className="rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage={t('knowledge.collectionCreated')}>
              <div className="mb-4 flex items-center gap-2"><Library aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">{t('knowledge.newCollection')}</h2></div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('knowledge.collectionNameLabel')}</span><Input className="h-11 w-full" name="name" placeholder={t('knowledge.qualityCompounders')} required /></label>
                <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('knowledge.collectionTypeLabel')}</span><select className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" name="collection_type" defaultValue="custom" required><option value="custom">{t('knowledge.collectionTypeCustom')}</option><option value="investor">{t('knowledge.collectionTypeInvestor')}</option><option value="theme">{t('knowledge.collectionTypeTheme')}</option></select></label>
                <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 sm:col-span-2"><span>{t('knowledge.collectionDescriptionLabel')}</span><Textarea className="min-h-[88px] w-full" name="description" placeholder={t('knowledge.collectionDescriptionPlaceholder')} /></label>
                <Button className="h-11 w-full sm:col-span-2 sm:w-fit" type="submit">{t('knowledge.createCollection')}</Button>
              </div>
            </MutationForm>

            <div className="rounded-xl border border-gray-800 bg-surface-1 p-5">
              <div className="mb-4 flex items-center gap-2"><Library aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">{t('knowledge.defaultsTitle')}</h2></div>
              {hasDefaultCollections(collections) ? <p className="text-sm text-gray-400">{t('knowledge.defaultsInstalled')}</p> : <MutationForm action={installKnowledgeDefaults} successMessage={t('knowledge.defaultsSuccess')}>
                <Button className="h-11 w-full sm:w-fit" type="submit"><Library aria-hidden="true" className="h-4 w-4" />{t('knowledge.defaultsInstall')}</Button>
              </MutationForm>}
            </div>
          </section>
        </TabsContent>

        <TabsContent className="mt-2" value={TABS.principios}>
      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center"><div className="flex items-center gap-2"><Sparkles aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="text-lg font-semibold text-gray-100">{t('knowledge.principlesTitle')}</h2></div><div className="flex flex-wrap gap-2 md:ml-auto">{['', 'proposed', 'approved', 'rejected', 'merged', 'superseded'].map((status) => <Button asChild className="min-h-[44px]" key={status || 'all'} size="sm" variant={(query.status ?? '') === status ? 'default' : 'outline'}><Link href={status ? `/knowledge?tab=principios&status=${status}` : '/knowledge?tab=principios'} scroll={false}>{Object.hasOwn(PRINCIPLE_STATUS_LABELS, status) ? t(PRINCIPLE_STATUS_LABELS[status]) : status}</Link></Button>)}</div></div>
        <PageNavigation offset={principleOffset} count={principles.length} total={library.principleTotal} parameter="principleOffset" tab="principios" status={query.status} t={t} />
        <div className="grid gap-4 xl:grid-cols-2">
          {visiblePrinciples.map((principle) => (
            <article className="min-w-0 rounded-lg border border-gray-800 bg-black/30 p-4 break-words" key={principle.id}>
              <div className="flex flex-wrap items-center gap-2"><Badge variant="outline" className={statusTone(principle.status)}>{label(principle.status, t)}</Badge><Badge variant="outline">{principle.category}</Badge><span className="text-xs text-gray-500">{t('knowledge.versionConfidence', { version: formatNumber(Number(principle.version), { maximumFractionDigits: 0 }, undefined, locale), confidence: formatPercent(Number(principle.confidence), { digits: 0 }, undefined, locale) })}</span></div>
              <h3 className="mt-3 font-semibold leading-6 text-gray-100">{principle.principle}</h3>
              <blockquote className="mt-3 border-l-2 border-teal-900 pl-3 text-sm italic leading-6 text-gray-400">{principle.exact_fragment}</blockquote>
              <div className="mt-3 text-xs text-gray-500">{documentNames.get(principle.knowledge_document_id) ?? t('knowledge.documentRef', { id: principle.knowledge_document_id })} · {t('knowledge.pageLabel', { page: principle.page_number === null || principle.page_number === undefined ? t('common.na') : formatNumber(principle.page_number, { maximumFractionDigits: 0 }, undefined, locale) })}</div>
              {principle.application_conditions.length ? <p className="mt-3 text-sm text-gray-300"><span className="font-semibold text-gray-400">{t('knowledge.applyWhen')}</span> {principle.application_conditions.join('; ')}</p> : null}
              {principle.exceptions.length ? <p className="mt-2 text-sm text-amber-200"><span className="font-semibold">{t('knowledge.exceptionsLabel')}</span> {principle.exceptions.join('; ')}</p> : null}
              {principle.semantic_duplicate_of_id ? <div className="mt-3 rounded border border-amber-900/60 bg-amber-950/20 p-2 text-xs text-amber-200">{t('knowledge.duplicateNotice', { id: principle.semantic_duplicate_of_id })}</div> : null}
              {principle.status === 'proposed' ? <div className="mt-4 flex flex-wrap gap-2"><MutationForm action={decideKnowledgePrinciple.bind(null, principle.id, 'approve')} successMessage={t('knowledge.principleApproved')}><Button className="min-h-[44px]" size="sm" type="submit"><Check aria-hidden="true" className="h-4 w-4" />{t('knowledge.approve')}</Button></MutationForm><MutationForm action={decideKnowledgePrinciple.bind(null, principle.id, 'reject')} successMessage={t('knowledge.principleRejected')}><Button className="min-h-[44px]" size="sm" type="submit" variant="outline"><X aria-hidden="true" className="h-4 w-4" />{t('knowledge.reject')}</Button></MutationForm>{principle.semantic_duplicate_of_id ? <MutationForm action={mergeKnowledgePrinciple.bind(null, principle.id, principle.semantic_duplicate_of_id)} successMessage={t('knowledge.principleMerged')}><Button className="min-h-[44px]" size="sm" type="submit" variant="outline">{t('knowledge.mergeDuplicate')}</Button></MutationForm> : null}</div> : null}
              {['proposed', 'approved'].includes(principle.status) ? <details className="mt-4 border-t border-gray-800 pt-3"><summary className="cursor-pointer text-xs font-semibold uppercase text-gray-500">{t('knowledge.correctAsNew')}</summary><MutationForm action={reviseKnowledgePrincipleResult.bind(null, principle.id)} className="mt-3 grid grid-cols-1 gap-2" successMessage={t('knowledge.revisionProposed')}><Textarea className="min-h-[88px] w-full text-base md:text-sm" defaultValue={principle.principle} name="principle" required /><Input className="h-11 w-full" defaultValue={principle.category} name="category" required /><Input className="h-11 w-full" defaultValue={principle.application_conditions.join(', ')} name="application_conditions" placeholder={t('knowledge.conditionsPlaceholder')} /><Input className="h-11 w-full" defaultValue={principle.exceptions.join(', ')} name="exceptions" placeholder={t('knowledge.exceptionsPlaceholder')} /><Button className="h-11 w-full sm:w-fit" size="sm" type="submit">{t('knowledge.createRevision')}</Button></MutationForm></details> : null}
            </article>
          ))}
          {!visiblePrinciples.length ? (
            library.principleTotal > 0 || query.status ? (
              <p className="text-sm text-gray-500">
                {t('knowledge.noPrincipleMatch')}{' '}
                <Link className="text-teal-300 underline underline-offset-2" href="/knowledge?tab=principios">{t('knowledge.viewAll')}</Link>
              </p>
            ) : (
              <div className="rounded-lg border border-dashed border-gray-800 p-4">
                <p className="text-sm text-gray-400">
                  {activeJobs.length
                    ? t('knowledge.extracting')
                    : noPrinciplesText(jobs, t)}
                </p>
                {!activeJobs.length ? (
                  <Button asChild className="mt-3 min-h-[44px]" size="sm" variant="outline">
                    <Link href="/knowledge">{t('knowledge.goToLibrary')}</Link>
                  </Button>
                ) : null}
              </div>
            )
          ) : null}
        </div>
        <PageNavigation offset={principleOffset} count={principles.length} total={library.principleTotal} parameter="principleOffset" tab="principios" status={query.status} t={t} />
      </section>
        </TabsContent>
      </Tabs>
    </main>
  );
}

function PageNavigation({ offset, count, total, parameter, tab, status, q, t }: {
  offset: number; count: number; total: number; parameter: string; tab: string; status?: string; q?: string; t: TranslateFn;
}) {
  const href = (next: number) => `/knowledge?${new URLSearchParams({ tab, [parameter]: String(next), ...(status ? { status } : {}), ...(q ? { q } : {}) })}`;
  if (offset === 0 && offset + count >= total) return null;
  return <nav aria-label={tab === 'principios' ? t('knowledge.pagesPrinciples') : t('knowledge.pagesDocuments')} className="my-4 flex flex-wrap items-center gap-3 text-sm text-gray-400">
    <span>{count ? t('knowledge.pagerRange', { start: offset + 1, end: offset + count, total }) : t('knowledge.pagerRangeZero', { total })}</span>
    {offset > 0 ? <Button asChild variant="outline" className="min-h-11"><Link href={href(Math.max(0, offset - KNOWLEDGE_PAGE_SIZE))}>{t('knowledge.pagerPrevious')}</Link></Button> : null}
    {offset + count < total ? <Button asChild variant="outline" className="min-h-11"><Link href={href(offset + KNOWLEDGE_PAGE_SIZE)}>{t('knowledge.pagerNext')}</Link></Button> : null}
  </nav>;
}
