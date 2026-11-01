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
import { createFormatters } from '@/lib/format';
import { getLocale, getT } from '@/lib/i18n/server';
import type { TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';
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

const SOURCE_TYPE_KEYS: Record<string, TranslationKey> = {
  manual_upload: 'research.sourcesPage.typeManualUpload', upload: 'research.sourcesPage.typeUpload',
  seed: 'research.sourcesPage.typeSeed', yahoo_fundamentals: 'research.sourcesPage.typeYahoo',
  YAHOO_FUNDAMENTALS: 'research.sourcesPage.typeYahoo', fmp_profile: 'research.sourcesPage.typeFmp',
  manual_transcript: 'research.sourcesPage.typeManualTranscript', filing: 'research.sourcesPage.typeFiling',
  company_ir: 'research.sourcesPage.typeCompanyIr', transcript: 'research.sourcesPage.typeTranscript',
};

/** En inglés las etiquetas curadas salen de las claves; los ids propios (SEC EDGAR, ESEF...) se quedan. */
function sourceTypeLabel(value: string, t?: TranslateFn): string {
  if (t && Object.hasOwn(SOURCE_TYPE_KEYS, value)) return t(SOURCE_TYPE_KEYS[value]);
  return SOURCE_TYPE_LABELS[value] ?? sourceDisplay(value, t ? 'en' : 'es');
}

const SOURCE_SCOPE_LABELS = {
  followed: 'Mi universo',
  all: 'Todas',
} as const;

const SOURCE_TYPE_FILTER_OPTIONS = Object.entries(SOURCE_TYPE_LABELS)
  .filter(([value]) => value !== 'YAHOO_FUNDAMENTALS');

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('research.sourcesMetaTitle') };
}

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
  const [t, locale] = await Promise.all([getT(), getLocale()]);
  const { formatDate, formatNumber, na: NA } = createFormatters(locale);
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
      return <BackendOffline feature={t('research.sourcesPage.feature')} retryHref={retryHref} />;
    }
    throw error;
  }
  const { documents, audits, documentsTotal, pageInfo } = sources;

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
      <header className="flex items-center justify-between gap-3 border-b border-gray-800 pb-4">
        <div className="flex items-center gap-3">
          <Button asChild className="min-w-11" size="sm" variant="ghost">
            <Link href="/research" aria-label={t('research.sourcesPage.back')}>
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            </Link>
          </Button>
          <h1 className="text-xl font-bold text-gray-100 sm:text-2xl">{t('research.sourcesPage.title')}</h1>
        </div>
        <div className="rounded-lg border border-gray-800 bg-surface-1 px-3 py-1.5 text-xs text-gray-400">
          {documentsTotal !== null
            ? ticker
              ? t('research.sourcesPage.docsOfTicker', { count: formatNumber(documentsTotal, { maximumFractionDigits: 0 }), ticker })
              : t('research.sourcesPage.docsCount', { count: formatNumber(documentsTotal, { maximumFractionDigits: 0 }) })
            : t('research.sourcesPage.docsOnPage', { count: formatNumber(documents.length, { maximumFractionDigits: 0 }) })}{' '}
          · {t('research.sourcesPage.auditsCount', { count: formatNumber(audits.length, { maximumFractionDigits: 0 }) })}{ticker ? ' (global)' : ''}
          {' '}· {scope === 'all' ? t('research.sourcesPage.scopeAll') : t('research.sourcesPage.scopeFollowed')}
        </div>
      </header>

      <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <FileText aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('research.sourcesPage.documents')}</h2>
        </div>
        <form action="/research/sources" className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-[220px_170px_220px_minmax(200px,1fr)_auto] xl:items-end" method="get">
          <label className="grid gap-1 text-xs font-medium text-gray-400" htmlFor="sources-ticker">
            {t('research.sourcesPage.filterTicker')}
            <TickerSearchInput
              className="min-h-11 min-w-0 border-gray-800 bg-black/30 text-gray-200"
              defaultValue={ticker}
              id="sources-ticker"
              name="ticker"
              placeholder={t('research.sourcesPage.tickerPlaceholder')}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium text-gray-400" htmlFor="sources-scope">
            {t('research.sourcesPage.scope')}
            <select
              className="h-11 rounded-lg border border-gray-800 bg-black px-3 text-base text-gray-200 sm:text-sm"
              defaultValue={scope}
              id="sources-scope"
              name="scope"
            >
              <option value="followed">{t('research.sourcesPage.scopeFollowed')}</option>
              <option value="all">{t('research.sourcesPage.scopeAll')}</option>
            </select>
          </label>
          <label className="grid gap-1 text-xs font-medium text-gray-400" htmlFor="sources-source-type">
            {t('research.sourcesPage.sourceType')}
            <select
              className="h-11 rounded-lg border border-gray-800 bg-black px-3 text-base text-gray-200 sm:text-sm"
              defaultValue={sourceType}
              id="sources-source-type"
              name="source_type"
            >
              <option value="">{t('research.sourcesPage.allTypes')}</option>
              {SOURCE_TYPE_FILTER_OPTIONS.map(([value, text]) => (
                <option key={value} value={value}>{locale === 'en' ? sourceTypeLabel(value, t) : text}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-medium text-gray-400" htmlFor="sources-q">
            {t('research.sourcesPage.search')}
            <Input
              className="min-h-11 h-10 border-gray-800 bg-black/30 text-gray-200"
              defaultValue={query}
              id="sources-q"
              name="q"
              placeholder={t('research.sourcesPage.searchPlaceholder')}
            />
          </label>
          <div className="flex flex-wrap items-center gap-3 sm:col-span-2 xl:col-span-1 xl:pb-0.5">
            <Button size="sm" type="submit" variant="outline">
              {t('research.sourcesPage.filter')}
            </Button>
            {ticker || sourceType || query || scope === 'all' ? (
              <Link className="text-sm text-teal-300 hover:text-teal-200" href={sourcesHref('', 1)}>
                {t('research.sourcesPage.clearFilters')}
              </Link>
            ) : null}
          </div>
        </form>
        {documentsTotal !== null && (pageInfo?.pages ?? 1) > 1 ? (
          <p className="mb-4 text-sm text-gray-500">
            {ticker
              ? t('research.sourcesPage.showingTicker', { from: formatNumber(pageInfo?.from ?? 0, { maximumFractionDigits: 0 }), to: formatNumber(pageInfo?.to ?? 0, { maximumFractionDigits: 0 }), total: formatNumber(documentsTotal, { maximumFractionDigits: 0 }), ticker })
              : t('research.sourcesPage.showing', { from: formatNumber(pageInfo?.from ?? 0, { maximumFractionDigits: 0 }), to: formatNumber(pageInfo?.to ?? 0, { maximumFractionDigits: 0 }), total: formatNumber(documentsTotal, { maximumFractionDigits: 0 }) })}{' '}
            {t('research.sourcesPage.sortNote')}
          </p>
        ) : null}
        <OverflowScrollRegion label={t('research.sourcesPage.regionLabel')}>
          <table className="w-full min-w-[820px] text-left text-sm">
            <caption className="sr-only">{t('research.sourcesPage.caption')}</caption>
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th className="border-b border-gray-800 py-2" scope="col">Ticker</th>
                <th className="border-b border-gray-800 py-2" scope="col">{t('research.sourcesPage.colTitle')}</th>
                <th className="border-b border-gray-800 py-2" scope="col">{t('research.sourcesPage.colSource')}</th>
                <th className="border-b border-gray-800 py-2" scope="col">{t('research.sourcesPage.colTier')}</th>
                <th className="border-b border-gray-800 py-2" scope="col">{t('research.sourcesPage.colPublished')}</th>
                <th className="border-b border-gray-800 py-2" scope="col">URL</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id} className="border-b border-gray-900 last:border-0">
                  <th className="py-3 text-left text-sm font-semibold text-gray-200" scope="row">{document.ticker ?? 'GLOBAL'}</th>
                  <td className="py-3 text-gray-300">
                    {document.source_url ? (
                      <a className="underline decoration-gray-700 underline-offset-4 transition hover:text-teal-200" href={document.source_url} rel="noreferrer" target="_blank">
                        {document.title}
                      </a>
                    ) : (
                      document.title
                    )}
                  </td>
                  <td className="py-3 text-gray-400">{sourceTypeLabel(document.source_type, locale === 'en' ? t : undefined)}</td>
                  <td className="py-3 text-gray-400">{sourceTierDisplay(document.source_tier, locale)}</td>
                  <td className="py-3 text-gray-500">
                    {document.published_at ? formatDate(document.published_at, undefined, NA) : t('research.sourcesPage.noDate')}
                  </td>
                  <td className="py-3 text-gray-500">
                    {document.source_url ? (
                      <a aria-label={t('research.sourcesPage.openSource', { title: document.title })} className="inline-flex min-h-11 min-w-11 items-center text-teal-300 hover:text-teal-200" href={document.source_url} rel="noreferrer" target="_blank">
                        {t('research.sourcesPage.open')}
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
                    <div className="w-full max-w-[calc(100vw-6rem)] text-left sm:mx-auto sm:w-fit sm:text-center">
                    {ticker ? (
                      <p>
                        {t('research.sourcesPage.emptyTicker', { ticker })}{' '}
                        <Link className="text-teal-300 hover:text-teal-200" href={sourcesHref('', 1, filters)}>
                          {t('research.sourcesPage.removeTickerFilter')}
                        </Link>
                      </p>
                    ) : scope === 'followed' ? (
                      <p>{t('research.sourcesPage.emptyFollowed')}</p>
                    ) : (
                      <p>{t('research.sourcesPage.emptyAll')}</p>
                    )}
                    {scope === 'followed' ? (
                      <div className="mx-auto mt-3 max-w-xl">
                        <p className="text-xs text-gray-500">
                          {t('research.sourcesPage.followedHint')}
                        </p>
                        <Link
                          className="mt-3 inline-flex items-center gap-2 rounded-md border border-teal-800 px-3 py-2 text-xs font-medium text-teal-300 hover:border-teal-600 hover:text-teal-200"
                          href={sourcesHref(ticker, 1, { scope: 'all', sourceType: sourceType || undefined, q: query || undefined })}
                        >
                          {t('research.sourcesPage.seeAll')}
                        </Link>
                      </div>
                    ) : sourceType || query ? (
                      <p className="mt-2 text-xs text-gray-500">
                        {t('research.sourcesPage.tryClearing')}{' '}
                        <Link className="text-teal-300 hover:text-teal-200" href={sourcesHref(ticker, 1, { scope })}>
                          {t('research.sourcesPage.clearFiltersLower')}
                        </Link>.
                      </p>
                    ) : (
                      <span className="mt-2 block text-xs text-gray-500">
                        {t('research.sourcesPage.emptyHint')}
                      </span>
                    )}
                    </div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </OverflowScrollRegion>
        {pageInfo && pageInfo.pages > 1 ? (
          <nav aria-label={t('research.sourcesPage.paginationAria')} className="mt-4 flex flex-wrap items-center gap-3 text-sm">
            {pageInfo.page > 1 ? (
              <Link
                className="inline-flex min-h-11 min-w-11 items-center rounded-lg border border-gray-700 px-3 py-1.5 text-gray-200 transition hover:border-teal-700"
                href={sourcesHref(ticker, pageInfo.page - 1, filters)}
              >
                {t('research.sourcesPage.prev')}
              </Link>
            ) : null}
            <span className="text-xs whitespace-nowrap text-gray-500">
              {t('research.pageOf', { current: formatNumber(pageInfo.page, { maximumFractionDigits: 0 }), total: formatNumber(pageInfo.pages, { maximumFractionDigits: 0 }) })}
            </span>
            {pageInfo.page < pageInfo.pages ? (
              <Link
                className="inline-flex min-h-11 min-w-11 items-center rounded-lg border border-gray-700 px-3 py-1.5 text-gray-200 transition hover:border-teal-700"
                href={sourcesHref(ticker, pageInfo.page + 1, filters)}
              >
                {t('research.sourcesPage.next')}
              </Link>
            ) : null}
          </nav>
        ) : null}
      </section>

        <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck aria-hidden="true" className="h-5 w-5 text-teal-300" />
            <h2 className="text-lg font-semibold text-gray-100">{t('research.sourcesPage.audits')}</h2>
          </div>
          <div className="grid gap-3">
            {audits.length > 8 ? (
              <p className="text-xs text-gray-500">{t('research.sourcesPage.auditsShown', { total: formatNumber(audits.length, { maximumFractionDigits: 0 }) })}</p>
            ) : null}
            {audits.slice(0, 8).map((audit) => (
              <div key={audit.id} className="rounded-md border border-gray-800 bg-black/30 p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className={audit.passed ? 'font-semibold text-teal-300' : 'font-semibold text-amber-300'}>
                    {auditStatusLabel(audit.passed, locale)}
                  </span>
                  <span className="text-sm text-gray-500" title={auditScoreText(audit.passed, audit.source_coverage_score, (value) => formatNumber(value, { maximumFractionDigits: 2 }), locale)}>{t('research.sourcesPage.citations', { score: formatNumber(audit.source_coverage_score, { maximumFractionDigits: 2 }) })}</span>
                </div>
                {audit.required_fixes.length ? (
                  <div className="mt-2 text-xs text-amber-200">{audit.required_fixes.map((fix) => auditFixLabel(fix, locale)).join(' ')}</div>
                ) : null}
              </div>
            ))}
            {!audits.length ? (
              <div className="rounded-md border border-dashed border-gray-800 p-4 text-center text-sm text-gray-500">
                <p>{t('research.sourcesPage.noAudits')}</p>
                <Link className="mt-3 inline-flex items-center gap-2 rounded-md border border-teal-800 px-3 py-2 text-xs font-medium text-teal-300 hover:border-teal-600 hover:text-teal-200" href={ticker ? `/research/${encodeURIComponent(ticker)}?view=thesis` : '/research'}>
                  {t('research.sourcesPage.generateThesis')}
                </Link>
              </div>
            ) : null}
          </div>
        </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">{t('research.sourcesPage.addSources')}</h2>
        <details className="rounded-lg border border-gray-800 bg-surface-1">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-200 hover:text-gray-100">{t('research.sourcesPage.pasteText')}</summary>
          <div className="border-t border-gray-800 p-4">
        <MutationForm action={importResearchSource} className="" showSuccessInline resetOnSuccess successMessage={t('research.sourcesPage.importedSource')}>
          <div className="grid gap-3">
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="ticker">{t('research.sourcesPage.fTicker')}</label>
              <TickerSearchInput id="ticker" name="ticker" placeholder={t('research.sourcesPage.tickerExample')} required />
            </div>
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="manual-source-type">{t('research.sourcesPage.sourceType')}</label>
              <select id="manual-source-type" name="source_type" defaultValue="manual_upload" className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:text-sm">
                <option value="manual_upload">{t('research.sourcesPage.optUserText')}</option>
                <option value="manual_transcript">{t('research.sourcesPage.typeTranscript')}</option>
                <option value="company_ir">{t('research.sourcesPage.typeCompanyIr')}</option>
              </select>
            </div>
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="period">{t('research.sourcesPage.fPeriod')}</label>
              <Input className="min-h-11" id="period" name="period" placeholder={t('research.sourcesPage.periodExample')} />
            </div>
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="title">{t('research.sourcesPage.colTitle')}</label>
              <Input className="min-h-11" id="title" name="title" placeholder={t('research.sourcesPage.titleExample')} required />
            </div>
            <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
              <label className="text-sm font-semibold text-gray-400" htmlFor="source_url">{t('research.sourcesPage.fUrl')}</label>
              <Input className="min-h-11" id="source_url" name="source_url" placeholder="https://..." />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-semibold text-gray-400" htmlFor="text">{t('research.sourcesPage.fText')}</label>
              <Textarea
                className="min-h-[260px] border-gray-800 bg-black/30 text-gray-200 focus-visible:ring-teal-500"
                id="text"
                name="text"
                placeholder={t('research.sourcesPage.textPlaceholder')}
                required
              />
            </div>
            <Button className="w-full sm:w-fit" type="submit">
              <UploadCloud aria-hidden="true" className="h-4 w-4" />
              {t('research.sourcesPage.importSource')}
            </Button>
          </div>
        </MutationForm>

          </div>
        </details>
        <details className="rounded-lg border border-gray-800 bg-surface-1">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-200 hover:text-gray-100">{t('research.sourcesPage.uploadSummary')}</summary>
          <div className="border-t border-gray-800 p-4">
          <MutationForm action={importResearchDocumentFile} className="" showSuccessInline resetOnSuccess successMessage={t('research.sourcesPage.importedDocument')}>
            <div className="grid gap-3">
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file-ticker">{t('research.sourcesPage.fTicker')}</label>
                <TickerSearchInput id="file-ticker" name="ticker" placeholder={t('research.sourcesPage.tickerExample')} required />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file-title">{t('research.sourcesPage.colTitle')}</label>
                <Input className="min-h-11" id="file-title" name="title" placeholder={t('research.sourcesPage.fileTitleExample')} required />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file-source-type">{t('research.sourcesPage.sourceType')}</label>
                <select id="file-source-type" name="source_type" defaultValue="manual_upload" className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:text-sm">{Object.entries(SOURCE_TYPE_LABELS).map(([value, text]) => <option key={value} value={value}>{locale === 'en' ? sourceTypeLabel(value, t) : text}</option>)}</select>
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file-source-url">{t('research.sourcesPage.fSourceUrl')}</label>
                <Input className="min-h-11" id="file-source-url" name="source_url" placeholder="https://..." />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="file">{t('research.sourcesPage.fFile')}</label>
                <FileUploadInput accept=".txt,.md,.html,.htm,.pdf,.docx,.xlsx,.csv,.tsv" id="file" name="file" required />
              </div>
              <Button className="w-full sm:w-fit" type="submit">
              <UploadCloud aria-hidden="true" className="h-4 w-4" />
              {t('research.sourcesPage.uploadDocument')}
              </Button>
            </div>
          </MutationForm>
          </div>
        </details>
        <details className="rounded-lg border border-gray-800 bg-surface-1">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-200 hover:text-gray-100">{t('research.sourcesPage.ingestSummary')}</summary>
          <div className="border-t border-gray-800 p-4">
          <MutationForm action={importResearchDocumentUrl} className="" showSuccessInline resetOnSuccess successMessage={t('research.sourcesPage.importedUrl')}>
            <div className="grid gap-3">
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="url-ticker">{t('research.sourcesPage.fTicker')}</label>
                <TickerSearchInput id="url-ticker" name="ticker" placeholder={t('research.sourcesPage.tickerExample')} required />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="url-title">{t('research.sourcesPage.colTitle')}</label>
                <Input className="min-h-11" id="url-title" name="title" placeholder={t('research.sourcesPage.urlTitleExample')} required />
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="url-source-type">{t('research.sourcesPage.sourceType')}</label>
                <select id="url-source-type" name="source_type" defaultValue="url" className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:text-sm">{Object.entries(SOURCE_TYPE_LABELS).map(([value, text]) => <option key={value} value={value}>{locale === 'en' ? sourceTypeLabel(value, t) : text}</option>)}</select>
              </div>
              <div className="grid gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
                <label className="text-sm font-semibold text-gray-400" htmlFor="url">{t('research.sourcesPage.fUrl')}</label>
                <Input className="min-h-11" id="url" name="url" placeholder="https://..." required type="url" />
              </div>
              <Button className="w-full sm:w-fit" type="submit" variant="outline">
              <UploadCloud aria-hidden="true" className="h-4 w-4" />
              {t('research.sourcesPage.ingestUrl')}
              </Button>
            </div>
          </MutationForm>
          </div>
        </details>
      </section>

    </main>
  );
}
