import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import type { Metadata } from 'next';
import Link from 'next/link';
import { BookOpen, Filter, Search as SearchIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import BackendOffline from '@/components/system/BackendOffline';
import { searchResearchLibrary } from '@/lib/actions/research-tools.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatDate, formatNumber, formatPercent } from '@/lib/format';
import { entityTypeDisplay, evidenceStatusDisplay, sourceDisplay, sourceTierDisplay } from '@/lib/research/source-display';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return {
    title: t('search.title'),
    description: t('search.metadataDescription'),
  };
}

type PageProps = {
  searchParams: Promise<{
    q?: string;
    ticker?: string;
    entity_types?: string;
    source_types?: string;
    statuses?: string;
    collection_id?: string;
    date_from?: string;
    date_to?: string;
    vector?: string;
  }>;
};

export default async function UniversalSearchPage({ searchParams }: PageProps) {
  const t = await getT();
  const query = await searchParams;
  const searched = Boolean(query.q?.trim());
  // El botón «Reintentar» de BackendOffline vuelve a la MISMA consulta: sin
  // estos parámetros el usuario perdería los filtros al reintentar.
  const currentParams = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value) currentParams.set(key, value);
  }
  const currentHref = currentParams.toString() ? `/search?${currentParams.toString()}` : '/search';

  // Sin consulta no hay llamada al backend (searchResearchLibrary cortocircuita)
  // y no puede haber estado de error: la pantalla es el formulario y la ayuda.
  let response: Awaited<ReturnType<typeof searchResearchLibrary>> | null = null;
  if (searched) {
    try {
      response = await searchResearchLibrary({
        query: query.q ?? '',
        ticker: query.ticker,
        entityTypes: query.entity_types,
        sourceTypes: query.source_types,
        statuses: query.statuses,
        collectionId: Number(query.collection_id) || undefined,
        dateFrom: query.date_from,
        dateTo: query.date_to,
        includeVector: query.vector !== 'false',
      });
    } catch (error) {
      // Antes el error subía al ErrorBoundary global: el usuario veía «Se
      // produjo un error inesperado» y no podía saber si había escrito mal la
      // consulta o el motor estaba apagado.
      if (isBackendUnavailableError(error)) {
        return <BackendOffline feature={t('search.title')} retryHref={currentHref} />;
      }
      throw error;
    }
  }

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-6 overflow-x-clip">
      <header className="flex flex-col gap-4 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase text-teal-300">{t('search.kicker')}</p>
          <h1 className="mt-1 text-3xl font-bold text-gray-100">{t('search.title')}</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">{t('search.subtitle')}</p>
        </div>
        <Button asChild className="h-11 w-full sm:w-auto" variant="outline"><Link href="/knowledge"><BookOpen aria-hidden="true" className="h-4 w-4" />{t('search.libraryLink')}</Link></Button>
      </header>

      <form className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5" method="get">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 flex-1"><span>{t('search.queryLabel')}</span><Input autoFocus className="h-11 w-full text-base" defaultValue={query.q} name="q" placeholder={t('search.queryPlaceholder')} required /></label>
          <Button className="h-11 w-full shrink-0 sm:w-auto" type="submit"><SearchIcon aria-hidden="true" className="h-4 w-4" />{t('search.submitSearch')}</Button>
        </div>
        <details className="mt-4">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-semibold text-gray-400"><Filter aria-hidden="true" className="h-4 w-4" />{t('search.advancedFilters')}</summary>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Ticker</span><TickerSearchInput className="h-11 w-full" defaultValue={query.ticker} name="ticker" placeholder="Ticker" /></label>
            <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('search.entityTypesLabel')}</span><Input className="h-11 w-full" defaultValue={query.entity_types} name="entity_types" placeholder={t('search.entityTypesPlaceholder')} /></label>
            <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('search.sourceTypesLabel')}</span><Input className="h-11 w-full" defaultValue={query.source_types} name="source_types" placeholder={t('search.sourceTypesPlaceholder')} /></label>
            <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('search.statusesLabel')}</span><Input className="h-11 w-full" defaultValue={query.statuses} name="statuses" placeholder={t('search.statusesPlaceholder')} /></label>
            <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('search.collectionIdLabel')}</span><Input className="h-11 w-full" defaultValue={query.collection_id} min="1" name="collection_id" placeholder={t('search.collectionIdLabel')} type="number" /></label>
            <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('search.dateFrom')}</span><Input aria-label={t('search.dateFrom')} className="h-11 w-full" defaultValue={query.date_from} name="date_from" type="date" /></label>
            <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('search.dateTo')}</span><Input aria-label={t('search.dateTo')} className="h-11 w-full" defaultValue={query.date_to} name="date_to" type="date" /></label>
            <label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('search.searchTypeLabel')}</span><select aria-label={t('search.searchTypeLabel')} className="h-11 w-full rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 md:text-sm" defaultValue={query.vector ?? 'true'} name="vector"><option value="true">{t('search.searchTypeHybrid')}</option><option value="false">{t('search.searchTypeLexical')}</option></select></label>
          </div>
        </details>
      </form>

      {response ? (
        <section className="grid min-w-0 grid-cols-1 gap-4">
          <div className="flex min-w-0 flex-col gap-3 rounded-xl border border-gray-800 bg-surface-1 p-4 md:flex-row md:items-center">
            <div><div className="text-sm font-semibold text-gray-100">{t('search.resultsFor', { count: formatNumber(response.total, { maximumFractionDigits: 0 }), query: response.query })}</div><div className="mt-1 text-xs text-gray-500">{t('search.rankingNote')}</div></div>
            {/* F322: los pares crudos de `retrieval` son diagnóstico interno
                del motor (fusiones, umbrales): visibles bajo demanda, no como
                badges primarios que parecen estado de la app. */}
            <details className="md:ml-auto">
              <summary className="cursor-pointer text-xs font-medium text-gray-400 hover:text-gray-200">{t('search.techDetailsSearch')}</summary>
              <div className="mt-2 flex flex-wrap gap-2">
                {Object.entries(response.retrieval).filter(([, value]) => typeof value === 'string').map(([key, value]) => <Badge key={key} variant="outline">{key}: {String(value)}</Badge>)}
              </div>
            </details>
          </div>

          {response.results.map((result, index) => (
            <article className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 break-words sm:p-5" key={`${result.entity_type}-${result.entity_id}`}>
              <div className="flex flex-col gap-3 md:flex-row md:items-start">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-950 text-sm font-semibold text-teal-300">{index + 1}</div>
                <div className="min-w-0 flex-1">
                  {/* F2: los ids internos del motor (document_chunk, tier_1_regulatory,
                      active) se etiquetan en es-ES; el localizador «entidad:id» y la
                      puntuación del reranker son diagnóstico y van plegados. */}
                  <div className="flex flex-wrap items-center gap-2"><Badge>{entityTypeDisplay(result.entity_type)}</Badge>{result.ticker ? <Badge variant="outline">{result.ticker}</Badge> : null}<Badge variant="outline">{sourceTierDisplay(result.source_tier)}</Badge><Badge variant="outline">{evidenceStatusDisplay(result.status)}</Badge></div>
                  <h2 className="mt-3 break-words text-lg font-semibold text-gray-100">{result.title}</h2>
                  <p className="mt-2 line-clamp-5 whitespace-pre-wrap text-sm leading-6 text-gray-300">{result.text}</p>
                  <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-500"><span>{result.collection ?? sourceDisplay(result.source_type)}</span><span>{formatDate(result.as_of, undefined, t('research.notAvailable'))}</span><span>{t('search.confidence', { value: formatPercent(result.source_trust, { digits: 0 }) })}</span></div>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-300">{t('search.techDetails')}</summary>
                    <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-500"><span>{t('search.reference', { value: result.citation })}</span><span>{t('search.score', { value: formatNumber(result.scores.reranker, { minimumFractionDigits: 4, maximumFractionDigits: 4 }) })}</span></div>
                  </details>
                </div>
              </div>
            </article>
          ))}
          {!response.results.length ? <div className="rounded-xl border border-dashed border-gray-800 p-8 text-center text-sm text-gray-500">{t('search.noEvidence')}</div> : null}
        </section>
      ) : (
        <section className="rounded-xl border border-dashed border-gray-800 p-10 text-center"><SearchIcon aria-hidden="true" className="mx-auto h-8 w-8 text-gray-500" /><h2 className="mt-3 font-semibold text-gray-300">{t('search.emptyTitle')}</h2><p className="mt-2 text-sm text-gray-500">{t('search.emptyExamples')}</p></section>
      )}
    </main>
  );
}
