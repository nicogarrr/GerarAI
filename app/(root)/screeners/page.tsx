import type { Metadata } from 'next';
import Link from 'next/link';
import { Calculator, ChevronDown, Filter, Play, Save } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { CriterionFields, CustomMetricFields, FormulaField, RankingFields } from '@/components/screeners/FilterFields';
import {
  createCustomMetric,
  createSavedScreen,
  updateSavedScreen,
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
import { formatDate, formatNumber, formatPercent, NA, NO_CORRIDO } from '@/lib/format';
import { t } from '@/lib/i18n/t';
import { formatScreenCriterionRight, formatScreenCriterionValue, formatScreenRank, screenCriterionMetricLabel, screenMissingFieldsLabel } from '@/lib/screener-results';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
  title: 'Screeners',
  description:
    'Fórmulas seguras contra el motor de análisis, con cobertura, confianza y ranking; filtros guardados y métricas personalizadas.',
};

type PageProps = { searchParams: Promise<{ left?: string; operator?: string; right?: string; ranking?: string; direction?: string; pagina?: string }> };
const operators: ScreenCriterion['operator'][] = ['>', '>=', '<', '<=', '==', '!='];

const RESULTS_PAGE_SIZE = 25;

function Results({ result, page, pageHref }: { result: ScreenResult; page: number; pageHref: (target: number) => string }) {
  const newMatches = new Set(result.new_match_company_ids ?? []);
  const matchedRows = result.results.filter(row => row.matched);
  // Paginación (preferencia del usuario) en vez de una tabla sin fin: el
  // móvil nunca ve una página de 980 px con scroll oculto.
  const totalPages = Math.max(1, Math.ceil(matchedRows.length / RESULTS_PAGE_SIZE));
  const currentPage = Math.min(totalPages, Math.max(1, page));
  const pageRows = matchedRows.slice((currentPage - 1) * RESULTS_PAGE_SIZE, currentPage * RESULTS_PAGE_SIZE);
  return (
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
      <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center"><div><h2 className="text-lg font-semibold text-gray-100">Resultados del filtro</h2><p className="text-sm text-gray-500">{formatNumber(result.match_count, { maximumFractionDigits: 0 })} {result.match_count === 1 ? 'coincidencia' : 'coincidencias'} en {formatNumber(result.company_count, { maximumFractionDigits: 0 })} {result.company_count === 1 ? 'empresa' : 'empresas'}</p></div>{result.ranking_formula ? <Badge className="md:ml-auto" variant="outline">ranking: {result.ranking_formula} · {result.ranking_direction}</Badge> : null}</div>
      {result.metrics_without_data && result.metrics_without_data.length > 0 ? <p className="mb-3 rounded-md border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-200" role="alert">Ninguna empresa tiene dato de: {screenMissingFieldsLabel(result.metrics_without_data)}. Revisa el nombre de la métrica; el filtro no puede coincidir con ella.</p> : null}
      {/*
        Misma <table> en el DOM en todos los viewports (accesibilidad): en <md
        cada fila es una tarjeta apilada con etiquetas por dato; desde md es
        tabla con scroll horizontal ANUNCIADO (OverflowScrollRegion).
      */}
      <OverflowScrollRegion label="Resultados del filtro">
        <table className="w-full text-left text-sm md:min-w-[980px]"><caption className="sr-only">Empresas que cumplen el filtro, con los criterios que cumple, ranking, cobertura de datos y confianza</caption><thead className="hidden text-xs uppercase text-gray-500 md:table-header-group"><tr><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap" scope="col">Empresa</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap" scope="col">Coincidencia</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap text-right" scope="col">Ranking</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap text-right" scope="col">Cobertura</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap text-right" scope="col">Confianza</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap" scope="col">Últimos datos</th><th className="border-b border-gray-800 px-3 py-2 whitespace-nowrap" scope="col">Faltantes</th></tr></thead><tbody className="block space-y-3 md:table-row-group md:space-y-0">
        {pageRows.map((row) => <tr className="block rounded-xl border border-gray-800 bg-gray-900/40 p-4 md:table-row md:rounded-none md:border-0 md:border-b md:border-gray-900 md:bg-transparent md:p-0" key={row.company_id}><th className="block py-1 text-left text-sm font-normal md:table-cell md:px-3 md:py-3" scope="row"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">Empresa</span><Link className="font-semibold text-teal-300 hover:text-teal-200" href={`/research/${row.ticker}`}>{row.ticker}</Link><div className="text-xs text-gray-500">{row.name}</div></th><td className="block py-1 text-xs text-gray-300 md:table-cell md:px-3 md:py-3"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">Coincidencia</span><ul className="flex flex-col gap-1">{row.criteria.map((criterion, index) => <li key={index}><span className="font-medium text-teal-300">{screenCriterionMetricLabel(criterion.left)} {formatScreenCriterionValue(criterion.left_value)}</span> <span className="text-gray-500">{criterion.operator} {formatScreenCriterionRight(criterion.right)}</span></li>)}</ul>{newMatches.has(row.company_id) ? <Badge className="mt-1">{t('screener.newMatch')}</Badge> : null}</td><td className="block py-1 text-gray-300 md:table-cell md:px-3 md:py-3 md:text-right"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">Ranking</span>{formatScreenRank(row.rank_value, result.ranking_formula)}</td><td className="block py-1 text-gray-300 md:table-cell md:px-3 md:py-3 md:text-right"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">Cobertura</span>{formatPercent(row.coverage_percent, { fromRatio: false, digits: 0 })}</td><td className="block py-1 text-gray-300 md:table-cell md:px-3 md:py-3 md:text-right"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">Confianza</span>{formatPercent(Number(row.confidence), { digits: 0 })}</td><td className="block py-1 text-gray-500 md:table-cell md:px-3 md:py-3"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">Últimos datos</span>{row.latest_data_at ? formatDate(row.latest_data_at) : NA}</td><td className="block py-1 text-amber-300 md:table-cell md:px-3 md:py-3"><span className="mb-0.5 block text-xs uppercase text-gray-500 md:hidden">Faltantes</span>{row.missing_fields.length ? screenMissingFieldsLabel(row.missing_fields) : NA}</td></tr>)}
      </tbody></table>
      </OverflowScrollRegion>
      {totalPages > 1 ? (
        <nav aria-label="Paginación de resultados" className="mt-4 flex items-center gap-2 text-sm text-gray-400">
          {currentPage > 1 ? <Link className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm text-gray-300 hover:bg-gray-800" href={pageHref(currentPage - 1)}>Anterior</Link> : null}
          <span>Página {formatNumber(currentPage, { maximumFractionDigits: 0 })} de {formatNumber(totalPages, { maximumFractionDigits: 0 })}</span>
          {currentPage < totalPages ? <Link className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm text-gray-300 hover:bg-gray-800" href={pageHref(currentPage + 1)}>Siguiente</Link> : null}
        </nav>
      ) : null}
      <p className="mt-3 text-xs text-gray-500">Solo se muestran coincidencias. {formatNumber(result.company_count - result.match_count, { maximumFractionDigits: 0 })} empresas no cumplen el filtro.</p>
    </section>
  );
}

export default async function ScreenersPage({ searchParams }: PageProps) {
  const query = await searchParams;
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
  let workspace: Awaited<ReturnType<typeof getScreenerWorkspace>>;
  try {
    workspace = await getScreenerWorkspace();
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature="Screeners" retryHref="/screeners" />;
    }
    throw error;
  }
  const { metrics, screens } = workspace;
  // Métricas con datos para sugerir en los datalist; null (engine caído o sin
  // endpoint) mantiene la lista estática completa.
  const metricCoverage = await getScreenerMetricCoverage();

  // El screener ad-hoc con fórmula inválida debe mostrar el error en un
  // banner visible en español, nunca escalar al boundary global.
  let result: ScreenResult | null = null;
  let screenError: string | null = null;
  // Envío con la condición incompleta (sin métrica o sin valor): el usuario
  // sí intentó ejecutar (la URL trae los parámetros del formulario) pero
  // runAdHocScreen no llega a consultar. Antes la página se recargaba sin
  // resultados y sin ningún aviso (bug QA live 21-oct-2026).
  const attemptedRun = query.left !== undefined || query.right !== undefined || query.ranking !== undefined;
  const incompleteRun = attemptedRun && (!query.left || !query.right);
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
    screenError = getErrorMessage(error) || 'La fórmula del screener no es válida. Revisa la sintaxis y reintenta.';
  }

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6 pb-28">
      <header className="border-b border-gray-800 pb-5"><p className="text-sm font-semibold uppercase text-teal-300">Descubrimiento de empresas</p><h1 className="mt-1 text-3xl font-bold text-gray-100">Screeners</h1></header>

      {/*
        Orden por lo que el usuario viene a ver: primero los resultados, luego
        el formulario que los produce. Antes los dos formularios de creación
        (ad-hoc y métrica) ocupaban la pantalla antes de cualquier resultado.
      */}
      {screenError ? (
        <div className="rounded-xl border border-red-800 bg-red-950/40 p-4 text-sm text-red-200" role="alert">
          <p className="font-semibold">No se pudo ejecutar el screener.</p>
          <p className="mt-1">{screenError}</p>
        </div>
      ) : null}
      {result ? <Results page={requestedPage} pageHref={resultsPageHref} result={result} /> : null}

      <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2"><Filter aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">Ejecutar un filtro ad-hoc</h2></div>
        {incompleteRun ? (
          <p role="alert" className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-200">
            El filtro no se ejecutó: falta la métrica o el valor de la condición. Complétalos y pulsa Ejecutar.
          </p>
        ) : null}
        <form className="space-y-4" method="get">
          <CriterionFields availableMetrics={metricCoverage ?? undefined} customMetrics={metrics} initialLeft={query.left ?? ''} initialOperator={operator} initialRight={query.right ?? ''} required />
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end"><RankingFields availableMetrics={metricCoverage ?? undefined} customMetrics={metrics} initialDirection={query.direction} initialFormula={query.ranking} /><SubmitButton /></div>
        </form>
      </section>

      <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><h2 className="font-semibold text-gray-100">Filtros guardados</h2><div className="mt-4 grid gap-3">{screens.map((screen) => <article className="rounded-lg border border-gray-800 bg-black/30 p-4" key={screen.id}><div className="flex items-start gap-3"><div><h3 className="font-semibold text-gray-200">{screen.name}</h3><p className="mt-1 text-xs text-gray-500">{formatNumber(screen.criteria.length, { maximumFractionDigits: 0 })} {screen.criteria.length === 1 ? 'criterio' : 'criterios'} · {screen.alerts_enabled ? 'alertas activadas' : 'alertas desactivadas'} · última {formatDate(screen.last_run_at, { day: 'numeric', month: 'short', year: 'numeric' }, NO_CORRIDO)}</p></div><Button asChild className="ml-auto" size="sm"><Link href={`/screeners/${screen.id}`}><Play aria-hidden="true" className="h-4 w-4" />Ejecutar</Link></Button></div>{screen.description ? <p className="mt-3 text-sm text-gray-400">{screen.description}</p> : null}
        <details className="mt-3"><summary className="cursor-pointer py-2 text-sm text-teal-300">Editar o eliminar</summary>
          <MutationForm action={updateSavedScreen} className="mt-3 grid gap-3" showSuccessInline>
            <input type="hidden" name="screen_id" value={screen.id} />
            <label className="text-sm">Nombre<Input name="name" defaultValue={screen.name} required /></label>
            <label className="text-sm">Descripción<Input name="description" defaultValue={screen.description} /></label>
            <label className="text-sm">Criterios (JSON)<textarea className="mt-1 w-full rounded border border-gray-700 bg-black p-2 font-mono text-xs" name="criteria_json" defaultValue={JSON.stringify(screen.criteria, null, 2)} rows={6} required /></label>
            <label className="text-sm">Ordenar por<Input name="ranking_formula" defaultValue={screen.ranking_formula ?? ''} /></label>
            <label className="text-sm">Dirección<select className="ml-3 rounded bg-black p-2" name="ranking_direction" defaultValue={screen.ranking_direction}><option value="desc">Mayor primero</option><option value="asc">Menor primero</option></select></label>
            <label className="text-sm"><input type="checkbox" name="alerts_enabled" defaultChecked={screen.alerts_enabled} /> Avisar de nuevas coincidencias</label>
            <Button type="submit" variant="outline">Guardar cambios</Button>
          </MutationForm>
          <MutationForm action={deleteSavedScreen} className="mt-5 grid gap-3" showSuccessInline>
            <input type="hidden" name="screen_id" value={screen.id} />
            <label className="text-sm text-gray-400"><input type="checkbox" name="confirm" required /> Eliminar este filtro y desactivar sus alertas. Se conserva el historial.</label>
            <Button type="submit" variant="outline">Eliminar filtro</Button>
          </MutationForm>
        </details></article>)}{!screens.length ? <p className="text-sm text-gray-500">Aún no hay filtros guardados.</p> : null}</div></section>

      {/* Los dos formularios de creación son configuración, no consulta: van
          plegados para que no compitan con los resultados ni con la lista. */}
      <details className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <summary className="flex min-h-[44px] cursor-pointer list-none items-center gap-2 font-semibold text-gray-100"><Save aria-hidden="true" className="h-5 w-5 text-teal-300" />Constructor visual de filtros<ChevronDown aria-hidden="true" className="ml-auto h-4 w-4 text-gray-500" /></summary>
        <div className="mt-4">
          <MutationForm action={createSavedScreen} resetOnSuccess successMessage="Filtro guardado">
            <div className="grid gap-3 sm:grid-cols-2">
              <div><label className="mb-1.5 block text-sm font-medium text-gray-200" htmlFor="screen-name">Nombre del filtro *</label><Input className="min-h-11" id="screen-name" name="name" placeholder="Calidad a precio razonable" required /></div>
              <div><label className="mb-1.5 block text-sm font-medium text-gray-200" htmlFor="screen-desc">Qué buscas (opcional)</label><Input className="min-h-11" id="screen-desc" name="description" placeholder="Empresas rentables con retorno superior al coste de capital" /></div>
            </div>
            <div className="mt-4 space-y-4">{([['', true], ['_2', false], ['_3', false]] as const).map(([suffix, required], index) => <CriterionFields availableMetrics={metricCoverage ?? undefined} customMetrics={metrics} key={suffix || 'one'} number={index + 1} required={required} suffix={suffix} />)}</div>
            <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(150px,190px)]"><FormulaField availableMetrics={metricCoverage ?? undefined} customMetrics={metrics} name="ranking_formula" title="Métrica para ordenar" /><div><label className="mb-1.5 block text-sm font-medium text-gray-200" htmlFor="saved-order">Dirección del orden</label><select className="min-h-11 w-full rounded-md border border-gray-700 bg-black px-3 text-sm text-gray-200" id="saved-order" name="ranking_direction" defaultValue="desc"><option value="desc">Mayor primero</option><option value="asc">Menor primero</option></select></div></div>
            <label className="mt-4 flex items-center gap-2 text-sm text-gray-300"><input name="alerts_enabled" type="checkbox" />Avisar de nuevas coincidencias</label>
            <Button className="mt-4" type="submit"><Save aria-hidden="true" className="h-4 w-4" />Guardar filtro</Button>
          </MutationForm>
        </div>
      </details>

      <details className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <summary className="flex min-h-[44px] cursor-pointer list-none items-center gap-2 font-semibold text-gray-100"><Calculator aria-hidden="true" className="h-5 w-5 text-teal-300" />Métrica personalizada<ChevronDown aria-hidden="true" className="ml-auto h-4 w-4 text-gray-500" /></summary>
        <div className="mt-4">
          <MutationForm action={createCustomMetric} resetOnSuccess successMessage="Métrica personalizada guardada">
            <CustomMetricFields />
            <Button className="mt-4" type="submit">Guardar métrica</Button>
          </MutationForm>
        </div>
      </details>

      <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><h2 className="font-semibold text-gray-100">Métricas personalizadas activas</h2><div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{metrics.map((metric) => <article className="rounded-lg border border-gray-800 bg-black/30 p-4" key={metric.id}><div className="flex items-center justify-between gap-3"><span className="font-semibold text-gray-200">{metric.name}</span><Badge variant="outline">v{metric.version}</Badge></div><code className="mt-3 block text-sm text-teal-300">{metric.metric_key} = {metric.formula}</code><p className="mt-2 text-xs text-gray-500">{metric.unit} · {metric.description || 'Sin descripción'}</p></article>)}{!metrics.length ? <p className="text-sm text-gray-500">Aún no hay métricas personalizadas.</p> : null}</div></section>
    </main>
  );
}
