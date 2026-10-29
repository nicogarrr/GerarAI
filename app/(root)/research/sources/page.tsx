import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft, FileText, ShieldCheck, UploadCloud } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { OverflowScrollRegion } from '@/components/ui/overflow-scroll-region';
import { Input } from '@/components/ui/input';
import { FileUploadInputLazy as FileUploadInput } from '@/components/forms/FileUploadInputLazy';
import { Textarea } from '@/components/ui/textarea';
import { MutationForm } from '@/components/forms/MutationForm';
import {
  getResearchSources,
  importResearchDocumentFile,
  importResearchDocumentUrl,
  importResearchSource,
} from '@/lib/actions/research.actions';
import { formatDate, formatNumber, NA } from '@/lib/format';
import { firstSearchParam, normalizeSourcesQuery, normalizeSourcesScope, normalizeSourcesTicker, normalizeSourcesType, sourcesHref } from '@/lib/research/sources-inventory';
import { auditScoreText, auditStatusLabel } from '@/lib/audit-status-copy';
import { auditFixLabel } from '@/lib/audit-status-copy';
import { sourceDisplay, sourceTierDisplay } from '@/lib/research/source-display';
import BackendOffline from '@/components/system/BackendOffline';
import { isBackendUnavailableError } from '@/lib/backend-offline';

/** F323: tipo y nivel de fuente llegan como ids internos en ingles
 *  (manual_upload, tier_1_regulatory...) y se pintaban en crudo en la tabla.
 *  Catálogo compartido en lib/research/source-display.ts (lo usa también la
 *  búsqueda universal): fallback que humaniza sin ocultar. */
/* Catálogo curado de la página: los selects de subida solo ofrecen tipos que
 * el usuario puede elegir; etiquetas nuevas del catálogo compartido se añaden
 * aquí a propósito, nunca por arrastre. */
const SOURCE_TYPE_LABELS: Record<string, string> = {
  sec: 'SEC EDGAR',
  esef: 'ESEF',
  cnmv: 'CNMV',
  url: 'URL',
  manual_upload: 'Subida manual',
  upload: 'Subida de archivo',
  manual: 'Manual',
  seed: 'Semilla inicial',
  fmp: 'FMP',
  yahoo_fundamentals: 'Yahoo Finance (fuente no oficial)',
  YAHOO_FUNDAMENTALS: 'Yahoo Finance (fuente no oficial)',
  fmp_profile: 'Perfil FMP',
  manual_transcript: 'Transcripción manual',
  filing: 'Documento regulatorio',
  company_ir: 'Relaciones con inversores',
  transcript: 'Transcripción',
};

function sourceTypeLabel(value: string): string {
  return SOURCE_TYPE_LABELS[value] ?? sourceDisplay(value);
}

function sourceTierLabel(value: string): string {
  return sourceTierDisplay(value);
}

const SOURCE_SCOPE_LABELS = {
  followed: 'Mi universo',
  all: 'Todas',
} as const;

const SOURCE_TYPE_FILTER_OPTIONS = Object.entries(SOURCE_TYPE_LABELS)
  .filter(([value]) => value !== 'YAHOO_FUNDAMENTALS');

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = { title: 'Fuentes' };

export default async function ResearchSourcesPage({
  searchParams,
}: {
  searchParams?: Promise<{
    ticker?: string | string[];
    page?: string | string[];
    scope?: string | string[];
    source_type?: string | string[];
    q?: string | string[];
  }>;
}) {
  const params = (await searchParams) ?? {};
  // Claves repetidas (?ticker=A&ticker=B) llegan como array: primer valor.
  const ticker = normalizeSourcesTicker(firstSearchParam(params.ticker));
  const scope = normalizeSourcesScope(firstSearchParam(params.scope));
  const sourceType = normalizeSourcesType(firstSearchParam(params.source_type));
  const query = normalizeSourcesQuery(firstSearchParam(params.q));
  const filters = { scope, sourceType: sourceType || undefined, q: query || undefined };
  const requestedPage = Number(firstSearchParam(params.page)) || 1;
  const requestedPageNumber = Number.isFinite(requestedPage) && requestedPage > 0 ? Math.floor(requestedPage) : 1;
  let sources: Awaited<ReturnType<typeof getResearchSources>>;
  try {
    sources = await getResearchSources({
      ticker: ticker || undefined,
      page: requestedPageNumber,
      scope,
      sourceType: sourceType || undefined,
      q: query || undefined,
    });
  } catch (error) {
    // Solo la caída reconocida del backend (red o 5xx) degrada a BackendOffline;
    // auth, 4xx y errores de programación siguen al error boundary de la ruta.
    if (isBackendUnavailableError(error)) {
      const retryHref = sourcesHref(ticker, requestedPageNumber, filters);
      return <BackendOffline feature="La sección de fuentes" retryHref={retryHref} />;
    }
    throw error;
  }
  const { documents, audits, documentsTotal, pageInfo } = sources;

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
      <header className="flex items-center justify-between gap-3 border-b border-gray-800 pb-4">
        <div className="flex items-center gap-3">
          <Button asChild className="min-w-11" size="sm" variant="ghost">
            <Link href="/research" aria-label="Volver a Research">
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            </Link>
          </Button>
          <h1 className="text-xl font-bold text-gray-100 sm:text-2xl">Fuentes</h1>
        </div>
        <div className="rounded-lg border border-gray-800 bg-surface-1 px-3 py-1.5 text-xs text-gray-400">
          {documentsTotal !== null
            ? ticker
              ? `${formatNumber(documentsTotal, { maximumFractionDigits: 0 })} documentos de ${ticker}`
              : `${formatNumber(documentsTotal, { maximumFractionDigits: 0 })} documentos`
            : `${formatNumber(documents.length, { maximumFractionDigits: 0 })} documentos en esta página`}{' '}
          · {formatNumber(audits.length, { maximumFractionDigits: 0 })} auditorías{ticker ? ' (global)' : ''}
          {' '}· {SOURCE_SCOPE_LABELS[scope]}
        </div>
      </header>

      <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <FileText aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Documentos</h2>
        </div>
        <form action="/research/sources" className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-[220px_170px_220px_minmax(200px,1fr)_auto] xl:items-end" method="get">
          <label className="grid gap-1 text-xs font-medium text-gray-400" htmlFor="sources-ticker">
            Filtrar por ticker
            <TickerSearchInput
              className="min-h-11 min-w-0 border-gray-800 bg-black/30 text-gray-200"
              defaultValue={ticker}
              id="sources-ticker"
              name="ticker"
              placeholder="Filtrar por ticker (p. ej. AAPL)"
            />
          </label>
          <label className="grid gap-1 text-xs font-medium text-gray-400" htmlFor="sources-scope">
            Alcance
            <select
              className="h-11 rounded-lg border border-gray-800 bg-black px-3 text-sm text-gray-200"
              defaultValue={scope}
              id="sources-scope"
              name="scope"
            >
              <option value="followed">Mi universo</option>
              <option value="all">Todas</option>
            </select>
          </label>
          <label className="grid gap-1 text-xs font-medium text-gray-400" htmlFor="sources-source-type">
            Tipo de fuente
            <select
              className="h-11 rounded-lg border border-gray-800 bg-black px-3 text-sm text-gray-200"
              defaultValue={sourceType}
              id="sources-source-type"
              name="source_type"
            >
              <option value="">Todos los tipos</option>
              {SOURCE_TYPE_FILTER_OPTIONS.map(([value, text]) => (
                <option key={value} value={value}>{text}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-medium text-gray-400" htmlFor="sources-q">
            Buscar
            <Input
              className="min-h-11 h-10 border-gray-800 bg-black/30 text-gray-200"
              defaultValue={query}
              id="sources-q"
              name="q"
              placeholder="Título o texto del documento"
            />
          </label>
          <div className="flex flex-wrap items-center gap-3 sm:col-span-2 xl:col-span-1 xl:pb-0.5">
            <Button size="sm" type="submit" variant="outline">
              Filtrar
            </Button>
            {ticker || sourceType || query || scope === 'all' ? (
              <Link className="text-sm text-teal-300 hover:text-teal-200" href={sourcesHref('', 1)}>
                Limpiar filtros
              </Link>
            ) : null}
          </div>
        </form>
        {documentsTotal !== null && (pageInfo?.pages ?? 1) > 1 ? (
          <p className="mb-4 text-sm text-gray-500">
            {ticker
              ? `Mostrando ${formatNumber(pageInfo?.from ?? 0, { maximumFractionDigits: 0 })}-${formatNumber(pageInfo?.to ?? 0, { maximumFractionDigits: 0 })} de ${formatNumber(documentsTotal, { maximumFractionDigits: 0 })} documentos de ${ticker}`
              : `Mostrando ${formatNumber(pageInfo?.from ?? 0, { maximumFractionDigits: 0 })}-${formatNumber(pageInfo?.to ?? 0, { maximumFractionDigits: 0 })} de ${formatNumber(documentsTotal, { maximumFractionDigits: 0 })}`}{' '}
            por fecha de publicación; los documentos sin fecha van al final.
          </p>
        ) : null}
        <OverflowScrollRegion label="Documentos importados">
          <table className="w-full min-w-[820px] text-left text-sm">
            <caption className="sr-only">Documentos, transcripts y auditorías que alimentan la evidencia, con fuente, nivel y fecha de publicación</caption>
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th className="border-b border-gray-800 py-2" scope="col">Ticker</th>
                <th className="border-b border-gray-800 py-2" scope="col">Título</th>
                <th className="border-b border-gray-800 py-2" scope="col">Fuente</th>
                <th className="border-b border-gray-800 py-2" scope="col">Nivel</th>
                <th className="border-b border-gray-800 py-2" scope="col">Publicado</th>
                <th className="border-b border-gray-800 py-2" scope="col">URL</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id} className="border-b border-gray-900 last:border-0">
                  <th className="py-3 text-left text-sm font-semibold text-gray-200" scope="row">{document.ticker ?? 'GLOBAL'}</th>
                  <td className="py-3 text-gray-300">{document.title}</td>
                  <td className="py-3 text-gray-400">{sourceTypeLabel(document.source_type)}</td>
                  <td className="py-3 text-gray-400">{sourceTierLabel(document.source_tier)}</td>
                  <td className="py-3 text-gray-500">
                    {document.published_at ? formatDate(document.published_at, undefined, NA) : 'sin fecha'}
                  </td>
                  <td className="py-3 text-gray-500">
                    {document.source_url ? (
                      <a className="inline-flex min-h-11 min-w-11 items-center text-teal-300 hover:text-teal-200" href={document.source_url} rel="noreferrer" target="_blank">
                        abrir
                      </a>
                    ) : (
                      NA
                    )}
                  </td>
                </tr>
              ))}
              {!documents.length ? (
                <tr>
                  <td className="py-6 text-center text-gray-500" colSpan={6}>
                    {ticker ? (
                      <p>
                        Sin documentos de {ticker}.{' '}
                        <Link className="text-teal-300 hover:text-teal-200" href={sourcesHref('', 1, filters)}>
                          Quitar el filtro de ticker
                        </Link>
                      </p>
                    ) : scope === 'followed' ? (
                      <p>Sin documentos en tu universo.</p>
                    ) : (
                      <p>Sin documentos importados.</p>
                    )}
                    {scope === 'followed' ? (
                      <div className="mx-auto mt-3 max-w-xl">
                        <p className="text-xs text-gray-500">
                          Esto no significa que no haya fuentes: tu universo puede no tener documentos con estos filtros.
                          Cambia el alcance a «Todas» para ver el inventario completo.
                        </p>
                        <Link
                          className="mt-3 inline-flex items-center gap-2 rounded-md border border-teal-800 px-3 py-2 text-xs font-medium text-teal-300 hover:border-teal-600 hover:text-teal-200"
                          href={sourcesHref(ticker, 1, { scope: 'all', sourceType: sourceType || undefined, q: query || undefined })}
                        >
                          Ver todas las fuentes
                        </Link>
                      </div>
                    ) : sourceType || query ? (
                      <p className="mt-2 text-xs text-gray-500">
                        Prueba a quitar el tipo de fuente o la búsqueda, o{' '}
                        <Link className="text-teal-300 hover:text-teal-200" href={sourcesHref(ticker, 1, { scope })}>
                          limpiar los filtros
                        </Link>.
                      </p>
                    ) : (
                      <span className="mt-2 block text-xs text-gray-500">
                        Usa los formularios de arriba para subir tu primer documento o ingerir una URL.
                      </span>
                    )}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </OverflowScrollRegion>
        {pageInfo && pageInfo.pages > 1 ? (
          <nav aria-label="Paginación de documentos" className="mt-4 flex flex-wrap items-center gap-3 text-sm">
            {pageInfo.page > 1 ? (
              <Link
                className="inline-flex min-h-11 min-w-11 items-center rounded-lg border border-gray-700 px-3 py-1.5 text-gray-200 transition hover:border-teal-700"
                href={sourcesHref(ticker, pageInfo.page - 1, filters)}
              >
                Anterior
              </Link>
            ) : null}
            <span className="text-xs text-gray-500">
              Página {formatNumber(pageInfo.page, { maximumFractionDigits: 0 })} de{' '}
              {formatNumber(pageInfo.pages, { maximumFractionDigits: 0 })}
            </span>
            {pageInfo.page < pageInfo.pages ? (
              <Link
                className="inline-flex min-h-11 min-w-11 items-center rounded-lg border border-gray-700 px-3 py-1.5 text-gray-200 transition hover:border-teal-700"
                href={sourcesHref(ticker, pageInfo.page + 1, filters)}
              >
                Siguiente
              </Link>
            ) : null}
          </nav>
        ) : null}
      </section>

        <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck aria-hidden="true" className="h-5 w-5 text-teal-300" />
            <h2 className="text-lg font-semibold text-gray-100">Auditorías de fuentes</h2>
          </div>
          <div className="grid gap-3">
            {audits.length > 8 ? (
              <p className="text-xs text-gray-500">Se muestran 8 de {formatNumber(audits.length, { maximumFractionDigits: 0 })} auditorías.</p>
            ) : null}
            {audits.slice(0, 8).map((audit) => (
              <div key={audit.id} className="rounded-md border border-gray-800 bg-black/30 p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className={audit.passed ? 'font-semibold text-teal-300' : 'font-semibold text-amber-300'}>
                    {auditStatusLabel(audit.passed)}
                  </span>
                  <span className="text-sm text-gray-500" title={auditScoreText(audit.passed, audit.source_coverage_score, (value) => formatNumber(value, { maximumFractionDigits: 2 }))}>Citas: {formatNumber(audit.source_coverage_score, { maximumFractionDigits: 2 })}/100</span>
                </div>
                {audit.required_fixes.length ? (
                  <div className="mt-2 text-xs text-amber-200">{audit.required_fixes.map(auditFixLabel).join(' ')}</div>
                ) : null}
              </div>
            ))}
            {!audits.length ? (
              <div className="rounded-md border border-dashed border-gray-800 p-4 text-center text-sm text-gray-500">
                <p>Sin auditorías todavía.</p>
                <Link className="mt-3 inline-flex items-center gap-2 rounded-md border border-teal-800 px-3 py-2 text-xs font-medium text-teal-300 hover:border-teal-600 hover:text-teal-200" href={ticker ? `/research/${encodeURIComponent(ticker)}?view=thesis` : '/research'}>
                  Genera una tesis para disparar la primera auditoría
                </Link>
              </div>
            ) : null}
          </div>
        </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">Añadir fuentes</h2>
        <details className="rounded-lg border border-gray-800 bg-surface-1">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-200 hover:text-gray-100">Pegar texto manualmente</summary>
          <div className="border-t border-gray-800 p-4">
        <MutationForm action={importResearchSource} className="" showSuccessInline resetOnSuccess successMessage="Fuente importada">
          <div className="grid gap-3">
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="ticker">Ticker</label>
              <TickerSearchInput id="ticker" name="ticker" placeholder="p. ej. ASTS" required />
            </div>
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="manual-source-type">Tipo de fuente</label>
              <select id="manual-source-type" name="source_type" defaultValue="manual_upload" className="h-11 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200">
                <option value="manual_upload">Texto aportado por el usuario</option>
                <option value="manual_transcript">Transcripción</option>
                <option value="company_ir">Relaciones con inversores</option>
              </select>
            </div>
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="period">Periodo</label>
              <Input className="min-h-11" id="period" name="period" placeholder="p. ej. Q2 2026" />
            </div>
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="title">Título</label>
              <Input className="min-h-11" id="title" name="title" placeholder="Transcript de la llamada de resultados del Q2" required />
            </div>
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="source_url">URL</label>
              <Input className="min-h-11" id="source_url" name="source_url" placeholder="https://..." />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-semibold text-gray-400" htmlFor="text">Texto</label>
              <Textarea
                className="min-h-[260px] border-gray-800 bg-black/30 text-gray-200 focus-visible:ring-teal-500"
                id="text"
                name="text"
                placeholder="Pega el transcript, la nota de RI, el artículo o el extracto del filing"
                required
              />
            </div>
            <Button className="w-full sm:w-fit" type="submit">
              <UploadCloud aria-hidden="true" className="h-4 w-4" />
              Importar fuente
            </Button>
          </div>
        </MutationForm>

          </div>
        </details>
        <details className="rounded-lg border border-gray-800 bg-surface-1">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-200 hover:text-gray-100">Subir un documento</summary>
          <div className="border-t border-gray-800 p-4">
          <MutationForm action={importResearchDocumentFile} className="" showSuccessInline resetOnSuccess successMessage="Documento importado">
            <div className="grid gap-3">
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file-ticker">Ticker</label>
                <TickerSearchInput id="file-ticker" name="ticker" placeholder="p. ej. ASTS" required />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file-title">Título</label>
                <Input className="min-h-11" id="file-title" name="title" placeholder="Informe anual, presentación, transcript..." required />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file-source-type">Tipo de fuente</label>
                <select id="file-source-type" name="source_type" defaultValue="manual_upload" className="h-11 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200">{Object.entries(SOURCE_TYPE_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select>
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file-source-url">URL de la fuente</label>
                <Input className="min-h-11" id="file-source-url" name="source_url" placeholder="https://..." />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file">Archivo</label>
                <FileUploadInput accept=".txt,.md,.html,.htm,.pdf,.docx,.xlsx,.csv,.tsv" id="file" name="file" required />
              </div>
              <Button className="w-full sm:w-fit" type="submit">
              <UploadCloud aria-hidden="true" className="h-4 w-4" />
              Subir documento
              </Button>
            </div>
          </MutationForm>
          </div>
        </details>
        <details className="rounded-lg border border-gray-800 bg-surface-1">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-200 hover:text-gray-100">Ingerir desde una URL</summary>
          <div className="border-t border-gray-800 p-4">
          <MutationForm action={importResearchDocumentUrl} className="" showSuccessInline resetOnSuccess successMessage="URL importada">
            <div className="grid gap-3">
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="url-ticker">Ticker</label>
                <TickerSearchInput id="url-ticker" name="ticker" placeholder="p. ej. ASTS" required />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="url-title">Título</label>
                <Input className="min-h-11" id="url-title" name="title" placeholder="Nota de prensa de RI o página del filing" required />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="url-source-type">Tipo de fuente</label>
                <select id="url-source-type" name="source_type" defaultValue="url" className="h-11 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200">{Object.entries(SOURCE_TYPE_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select>
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="url">URL</label>
                <Input className="min-h-11" id="url" name="url" placeholder="https://..." required type="url" />
              </div>
              <Button className="w-full sm:w-fit" type="submit" variant="outline">
              <UploadCloud aria-hidden="true" className="h-4 w-4" />
              Ingerir URL
              </Button>
            </div>
          </MutationForm>
          </div>
        </details>
      </section>

    </main>
  );
}
