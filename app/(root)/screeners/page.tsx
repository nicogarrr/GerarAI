import { Suspense } from 'react';
import type { Metadata } from 'next';
import Link from 'next/link';
import { Calculator, ChevronDown, Filter, Play, Save } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { CriterionFields, CustomMetricFields, FormulaField, RankingFields } from '@/components/screeners/FilterFields';
import {
  createCustomMetricResult,
  createSavedScreenResult,
  updateSavedScreenResult,
  deleteSavedScreen,
  getScreenerMetricCoverage,
  getScreenerWorkspace,
  runAdHocScreen,
  type ScreenCriterion,
  type ScreenResult,
} from '@/lib/actions/research-tools.actions';
import BackendOffline from '@/components/system/BackendOffline';
import { OverflowScrollRegion } from '@/components/ui/overflow-scroll-region';
import { SubmitButton } from '@/components/screeners/SubmitButton';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getErrorMessage } from '@/lib/types/errors';
import type { Formatters } from '@/lib/format';
import { getFormat, getT } from '@/lib/i18n/server';
import type { TranslateFn } from '@/lib/i18n/translate';
import { formatScreenCriterionRight, formatScreenCriterionValue, formatScreenRank, screenCriterionMetricLabel, screenMissingFieldsLabel } from '@/lib/screener-results';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: 'Screeners', description: t('screener.screens.metaDescription') };
}

type PageProps = { searchParams: Promise<{ left?: string; operator?: string; right?: string; ranking?: string; direction?: string; pagina?: string }> };
const operators: ScreenCriterion['operator'][] = ['>', '>=', '<', '<=', '==', '!='];

const RESULTS_PAGE_SIZE = 25;

function Results({ result, page, pageHref, t, fmt }: { result: ScreenResult; page: number; pageHref: (target: number) => string; t: TranslateFn; fmt: Formatters }) {
  const { formatDate, formatNumber, formatPercent, na: NA } = fmt;
  const count = (value: number) => formatNumber(value, { maximumFractionDigits: 0 });
  const newMatches = new Set(result.new_match_company_ids ?? []);
  const matchedRows = result.results.filter(row => row.matched);
  // Paginación (preferencia del usuario) en vez de una tabla sin fin: el
  // móvil nunca ve una página de 980 px con scroll oculto.
  const totalPages = Math.max(1, Math.ceil(matchedRows.length / RESULTS_PAGE_SIZE));
  const currentPage = Math.min(totalPages, Math.max(1, page));
  const pageRows = matchedRows.slice((currentPage - 1) * RESULTS_PAGE_SIZE, currentPage * RESULTS_PAGE_SIZE);
  return (
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
      <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center"><div><h2 className="text-lg font-semibold text-gray-100">{t('screener.screens.resultsTitle')}</h2><p className="text-sm text-gray-500">{result.match_count === 1 ? t('screener.screens.matchesOne', { count: count(1) }) : t('screener.screens.matchesMany', { count: count(result.match_count) })} {result.company_count === 1 ? t('screener.screens.inCompaniesOne', { count: count(1) }) : t('screener.screens.inCompaniesMany', { count: count(result.company_count) })}</p></div>{result.ranking_formula ? <Badge className="md:ml-auto" variant="outline">ranking: {result.ranking_formula} · {result.ranking_direction}</Badge> : null}</div>
      {result.metrics_without_data && result.metrics_without_data.length > 0 ? <p className="mb-3 rounded-md border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-200" role="alert">{t('screener.screens.noDataFor', { fields: screenMissingFieldsLabel(result.metrics_without_data, fmt.locale) })}</p> : null}
      {/*
        Misma <table> en el DOM en todos los viewports (accesibilidad): en <md
        cada fila es una tarjeta apilada con etiquetas por dato; desde md es
        tabla con scroll horizontal ANUNCIADO (OverflowScrollRegion).
      */}
      <OverflowScrollRegion label={t('screener.screens.resultsTitle')}>
        <table className="w-full text-left text-sm md:min-w-[980px]"><caption className="sr-only">{t('screener.screens.caption')}</caption><thead className="hidden text-xs uppercase text-gray-500 md:table-header-group"><tr><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap" scope="col">{t('screener.screens.colCompany')}</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap" scope="col">{t('screener.screens.colMatch')}</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap text-right" scope="col">{t('screener.screens.colRanking')}</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap text-right" scope="col">{t('screener.screens.colCoverage')}</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap text-right" scope="col">{t('screener.screens.colConfidence')}</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap" scope="col">{t('screener.screens.colLatest')}</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap" scope="col">{t('screener.screens.colMissing')}</th></tr></thead><tbody className="block space-y-3 md:table-row-group md:space-y-0">
        {pageRows.map((row) => <tr className="block rounded-xl border border-gray-800 bg-gray-900/40 p-4 md:table-row md:rounded-none md:border-0 md:border-b md:border-gray-900 md:bg-transparent md:p-0" key={row.company_id}><th className="block py-1 text-left text-sm font-normal md:table-cell md:px-3 md:py-3" scope="row"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">{t('screener.screens.colCompany')}</span><Link className="font-semibold text-teal-300 hover:text-teal-200" href={`/research/${row.ticker}`}>{row.ticker}</Link><div className="text-xs text-gray-500">{row.name}</div></th><td className="block py-1 text-xs text-gray-300 md:table-cell md:px-3 md:py-3"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">{t('screener.screens.colMatch')}</span><ul className="flex flex-col gap-1">{row.criteria.map((criterion, index) => <li key={index}><span className="font-medium text-teal-300">{screenCriterionMetricLabel(criterion.left, fmt.locale)} {formatScreenCriterionValue(criterion.left_value, fmt.locale)}</span> <span className="text-gray-500">{criterion.operator} {formatScreenCriterionRight(criterion.right, fmt.locale)}</span></li>)}</ul>{newMatches.has(row.company_id) ? <Badge className="mt-1">{t('screener.newMatch')}</Badge> : null}</td><td className="block py-1 text-gray-300 md:table-cell md:px-3 md:py-3 md:text-right"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">{t('screener.screens.colRanking')}</span>{formatScreenRank(row.rank_value, result.ranking_formula, fmt.locale)}</td><td className="block py-1 text-gray-300 md:table-cell md:px-3 md:py-3 md:text-right"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">{t('screener.screens.colCoverage')}</span>{formatPercent(row.coverage_percent, { fromRatio: false, digits: 0 })}</td><td className="block py-1 text-gray-300 md:table-cell md:px-3 md:py-3 md:text-right"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">{t('screener.screens.colConfidence')}</span>{formatPercent(Number(row.confidence), { digits: 0 })}</td><td className="block py-1 text-gray-500 md:table-cell md:px-3 md:py-3"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">{t('screener.screens.colLatest')}</span>{row.latest_data_at ? formatDate(row.latest_data_at) : NA}</td><td className="block py-1 text-amber-300 md:table-cell md:px-3 md:py-3"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">{t('screener.screens.colMissing')}</span>{row.missing_fields.length ? screenMissingFieldsLabel(row.missing_fields, fmt.locale) : NA}</td></tr>)}
      </tbody></table>
      </OverflowScrollRegion>
      {totalPages > 1 ? (
        <nav aria-label={t('screener.screens.pagingAria')} className="mt-4 flex items-center gap-2 text-sm text-gray-400">
          {currentPage > 1 ? <Link className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm text-gray-300 hover:bg-gray-800" href={pageHref(currentPage - 1)}>{t('screener.screens.prev')}</Link> : null}
          <span>{t('screener.screens.pageOf', { page: count(currentPage), total: count(totalPages) })}</span>
          {currentPage < totalPages ? <Link className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm text-gray-300 hover:bg-gray-800" href={pageHref(currentPage + 1)}>{t('screener.screens.next')}</Link> : null}
        </nav>
      ) : null}
      <p className="mt-3 text-xs text-gray-500">{t('screener.screens.onlyMatches', { count: count(result.company_count - result.match_count) })}</p>
    </section>
  );
}


async function ResultsSection({ query, operator, incompleteRun, requestedPage, resultsPageHref }: {
  query: { left?: string; operator?: string; right?: string; ranking?: string; direction?: string };
  operator: ScreenCriterion['operator'];
  incompleteRun: boolean;
  requestedPage: number;
  resultsPageHref: (target: number) => string;
}) {
  const t = await getT();
  const fmt = await getFormat();
  // El screener ad-hoc con fórmula inválida debe mostrar el error en un
  // banner visible en español, nunca escalar al boundary global.
  let result: ScreenResult | null = null;
  let screenError: string | null = null;
  try {
    result = incompleteRun ? null : await runAdHocScreen({
      left: query.left ?? '',
      operator,
      right: query.right ?? '',
      rankingFormula: query.ranking,
      rankingDirection: query.direction === 'asc' ? 'asc' : 'desc',
    });
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature="Screeners" retryHref="/screeners" />;
    }
    screenError = getErrorMessage(error) || t('screener.screens.formulaInvalid');
  }


  return (
    <>
      {screenError ? (
        <div className="rounded-xl border border-red-800 bg-red-950/40 p-4 text-sm text-red-200" role="alert">
          <p className="font-semibold">{t('screener.screens.runFailed')}</p>
          <p className="mt-1">{screenError}</p>
        </div>
      ) : null}
      {result ? <Results page={requestedPage} pageHref={resultsPageHref} result={result} t={t} fmt={fmt} /> : null}
    </>
  );
}

function ScreenersBodySkeleton() {
  return (
    <>
      <section aria-hidden="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <Skeleton className="h-5 w-56" />
        <Skeleton className="mt-4 h-11 w-full" />
        <Skeleton className="mt-3 h-11 w-full" />
        <Skeleton className="mt-3 h-11 w-2/3" />
      </section>
      <section aria-hidden="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="mt-4 h-24 w-full" />
      </section>
    </>
  );
}

async function WorkspaceSections({ query, operator, incompleteRun }: {
  query: { left?: string; operator?: string; right?: string; ranking?: string; direction?: string };
  operator: ScreenCriterion['operator'];
  incompleteRun: boolean;
}) {
  // Las dos peticiones se disparan a la vez (antes eran secuenciales: la
  // cobertura esperaba a que terminara todo el workspace).
  const workspacePromise = getScreenerWorkspace();
  const coveragePromise = getScreenerMetricCoverage();
  let workspace: Awaited<ReturnType<typeof getScreenerWorkspace>>;
  try {
    workspace = await workspacePromise;
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature="Screeners" retryHref="/screeners" />;
    }
    throw error;
  }
  const { metrics, screens } = workspace;
  // Métricas con datos para sugerir en los datalist; null (engine caído o sin
  // endpoint) mantiene la lista estática completa.
  const metricCoverage = await coveragePromise;
  const t = await getT();
  const { formatDate, formatNumber } = await getFormat();
  return (
    <>
   <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2"><Filter aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">{t('screener.screens.adhocTitle')}</h2></div>
        {incompleteRun ? (
          <p role="alert" className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-200">
            {t('screener.screens.incomplete')}
          </p>
        ) : null}
        <form className="space-y-4" method="get">
          <CriterionFields availableMetrics={metricCoverage ?? undefined} customMetrics={metrics} initialLeft={query.left ?? ''} initialOperator={operator} initialRight={query.right ?? ''} required />
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end"><RankingFields availableMetrics={metricCoverage ?? undefined} customMetrics={metrics} initialDirection={query.direction} initialFormula={query.ranking} /><SubmitButton /></div>
        </form>
      </section>

      <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><h2 className="font-semibold text-gray-100">{t('screener.screens.savedTitle')}</h2><div className="mt-4 grid gap-3">{screens.map((screen) => <article className="rounded-lg border border-gray-800 bg-black/30 p-4" key={screen.id}><div className="flex items-start gap-3"><div><h3 className="font-semibold text-gray-200">{screen.name}</h3><p className="mt-1 text-xs text-gray-500">{screen.criteria.length === 1 ? t('screener.screens.criteriaOne', { count: formatNumber(1, { maximumFractionDigits: 0 }) }) : t('screener.screens.criteriaMany', { count: formatNumber(screen.criteria.length, { maximumFractionDigits: 0 }) })} · {screen.alerts_enabled ? t('screener.screens.alertsOn') : t('screener.screens.alertsOff')} · {t('screener.screens.lastRun', { date: formatDate(screen.last_run_at, { day: 'numeric', month: 'short', year: 'numeric' }, t('screener.screens.notRun')) })}</p></div><Button asChild className="ml-auto" size="sm"><Link href={`/screeners/${screen.id}`}><Play aria-hidden="true" className="h-4 w-4" />{t('screener.screens.run')}</Link></Button></div>{screen.description ? <p className="mt-3 text-sm text-gray-400">{screen.description}</p> : null}
        <details className="mt-3"><summary className="cursor-pointer py-2 text-sm text-teal-300">{t('screener.screens.editOrDelete')}</summary>
          <MutationForm action={updateSavedScreenResult} className="mt-3 grid gap-3" showSuccessInline>
            <input type="hidden" name="screen_id" value={screen.id} />
            <label className="text-sm">{t('screener.screens.name')}<Input name="name" defaultValue={screen.name} required /></label>
            <label className="text-sm">{t('screener.screens.description')}<Input name="description" defaultValue={screen.description} /></label>
            <label className="text-sm">{t('screener.screens.criteriaJson')}<textarea className="mt-1 w-full rounded border border-gray-700 bg-black p-2 font-mono text-base sm:text-xs" name="criteria_json" defaultValue={JSON.stringify(screen.criteria, null, 2)} rows={6} required /></label>
            <label className="text-sm">{t('screener.screens.orderBy')}<Input name="ranking_formula" defaultValue={screen.ranking_formula ?? ''} /></label>
            <label className="text-sm">{t('screener.screens.direction')}<select className="ml-3 rounded bg-black p-2" name="ranking_direction" defaultValue={screen.ranking_direction}><option value="desc">{t('screener.screens.desc')}</option><option value="asc">{t('screener.screens.asc')}</option></select></label>
            <label className="text-sm"><input type="checkbox" name="alerts_enabled" defaultChecked={screen.alerts_enabled} /> {t('screener.screens.notify')}</label>
            <Button type="submit" variant="outline">{t('screener.screens.saveChanges')}</Button>
          </MutationForm>
          <MutationForm action={deleteSavedScreen} className="mt-5 grid gap-3" showSuccessInline>
            <input type="hidden" name="screen_id" value={screen.id} />
            <label className="text-sm text-gray-400"><input type="checkbox" name="confirm" required /> {t('screener.screens.deleteConfirm')}</label>
            <Button type="submit" variant="outline">{t('screener.screens.deleteFilter')}</Button>
          </MutationForm>
        </details></article>)}{!screens.length ? <p className="text-sm text-gray-500">{t('screener.screens.noSaved')}</p> : null}</div></section>

      {/* Los dos formularios de creación son configuración, no consulta: van
          plegados para que no compitan con los resultados ni con la lista. */}
      <details className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <summary className="flex min-h-[44px] cursor-pointer list-none items-center gap-2 font-semibold text-gray-100"><Save aria-hidden="true" className="h-5 w-5 text-teal-300" />{t('screener.screens.builder')}<ChevronDown aria-hidden="true" className="ml-auto h-4 w-4 text-gray-500" /></summary>
        <div className="mt-4">
          <MutationForm action={createSavedScreenResult} resetOnSuccess successMessage={t('screener.screens.savedOk')}>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><label className="mb-1.5 block text-sm font-medium text-gray-200" htmlFor="screen-name">{t('screener.screens.filterName')}</label><Input className="min-h-11" id="screen-name" name="name" placeholder={t('screener.screens.namePlaceholder')} required /></div>
              <div><label className="mb-1.5 block text-sm font-medium text-gray-200" htmlFor="screen-desc">{t('screener.screens.lookingFor')}</label><Input className="min-h-11" id="screen-desc" name="description" placeholder={t('screener.screens.descPlaceholder')} /></div>
            </div>
            <div className="mt-4 space-y-4">{([['', true], ['_2', false], ['_3', false]] as const).map(([suffix, required], index) => <CriterionFields availableMetrics={metricCoverage ?? undefined} customMetrics={metrics} key={suffix || 'one'} number={index + 1} required={required} suffix={suffix} />)}</div>
            <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(150px,190px)]"><FormulaField availableMetrics={metricCoverage ?? undefined} customMetrics={metrics} name="ranking_formula" title={t('screener.screens.rankMetric')} /><div><label className="mb-1.5 block text-sm font-medium text-gray-200" htmlFor="saved-order">{t('screener.screens.orderDirection')}</label><select className="min-h-11 w-full rounded-md border border-gray-700 bg-black px-3 text-base text-gray-200 sm:text-sm" id="saved-order" name="ranking_direction" defaultValue="desc"><option value="desc">{t('screener.screens.desc')}</option><option value="asc">{t('screener.screens.asc')}</option></select></div></div>
            <label className="mt-4 flex items-center gap-2 text-sm text-gray-300"><input name="alerts_enabled" type="checkbox" />{t('screener.screens.notify')}</label>
            <Button className="mt-4" type="submit"><Save aria-hidden="true" className="h-4 w-4" />{t('screener.screens.saveFilter')}</Button>
          </MutationForm>
        </div>
      </details>

      <details className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <summary className="flex min-h-[44px] cursor-pointer list-none items-center gap-2 font-semibold text-gray-100"><Calculator aria-hidden="true" className="h-5 w-5 text-teal-300" />{t('screener.screens.customMetric')}<ChevronDown aria-hidden="true" className="ml-auto h-4 w-4 text-gray-500" /></summary>
        <div className="mt-4">
          <MutationForm action={createCustomMetricResult} resetOnSuccess successMessage={t('screener.screens.metricSaved')}>
            <CustomMetricFields />
            <Button className="mt-4" type="submit">{t('screener.screens.saveMetric')}</Button>
          </MutationForm>
        </div>
      </details>

      <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><h2 className="font-semibold text-gray-100">{t('screener.screens.activeMetrics')}</h2><div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{metrics.map((metric) => <article className="rounded-lg border border-gray-800 bg-black/30 p-4" key={metric.id}><div className="flex items-center justify-between gap-3"><span className="font-semibold text-gray-200">{metric.name}</span><Badge variant="outline">v{metric.version}</Badge></div><code className="mt-3 block text-sm text-teal-300">{metric.metric_key} = {metric.formula}</code><p className="mt-2 text-xs text-gray-500">{metric.unit} · {metric.description || t('screener.screens.noDescription')}</p></article>)}{!metrics.length ? <p className="text-sm text-gray-500">{t('screener.screens.noMetrics')}</p> : null}</div></section>
    </>
  );
}


export default async function ScreenersPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const t = await getT();
  // Página de resultados (?pagina=N); los enlaces conservan el filtro intacto.
  const parsedPage = Number(query.pagina);
  const requestedPage = Number.isInteger(parsedPage) && parsedPage >= 1 ? Math.floor(parsedPage) : 1;
  const resultsPageHref = (target: number) => {
    const params = new URLSearchParams();
    for (const key of ['left', 'operator', 'right', 'ranking', 'direction'] as const) {
      const value = query[key];
      if (value) params.set(key, value);
    }
    if (target > 1) params.set('pagina', String(target));
    const qs = params.toString();
    return qs ? `/screeners?${qs}` : '/screeners';
  };
  const operator = operators.includes(query.operator as ScreenCriterion['operator']) ? query.operator as ScreenCriterion['operator'] : '>=';
  const attemptedRun = query.left !== undefined || query.right !== undefined || query.ranking !== undefined;
  const incompleteRun = attemptedRun && (!query.left || !query.right);

  // La cabecera y el layout pintan en el primer chunk; los datos del backend
  // llegan por streaming dentro de sus <Suspense> (antes el primer byte
  // útil esperaba a workspace + cobertura: LCP medido 15,5 s en prod).
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6 pb-28">
      <header className="border-b border-gray-800 pb-5"><p className="text-sm font-semibold uppercase text-teal-300">{t('screener.screens.eyebrow')}</p><h1 className="mt-1 text-3xl font-bold text-gray-100">Screeners</h1></header>

      {/*
        Orden por lo que el usuario viene a ver: primero los resultados, luego
        el formulario que los produce. Antes los dos formularios de creación
        (ad-hoc y métrica) ocupaban la pantalla antes de cualquier resultado.
      */}
      {attemptedRun && !incompleteRun ? (
        <Suspense fallback={null}>
          <ResultsSection incompleteRun={incompleteRun} operator={operator} query={query} requestedPage={requestedPage} resultsPageHref={resultsPageHref} />
        </Suspense>
      ) : null}
      <Suspense fallback={<ScreenersBodySkeleton />}>
        <WorkspaceSections incompleteRun={incompleteRun} operator={operator} query={query} />
      </Suspense>
    </main>
  );
}
