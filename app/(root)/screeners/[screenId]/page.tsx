import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScreenBreadcrumbName } from '@/components/screeners/ScreenBreadcrumbName';
import { getScreenerWorkspace, runSavedScreen } from '@/lib/actions/research-tools.actions';
import { formatNumber, formatPercent } from '@/lib/format';
import { t } from '@/lib/i18n/t';
import { formatScreenCriterionRight, formatScreenRank, screenCriterionMetricLabel, screenMissingDataEntry, screenMissingFieldsLabel } from '@/lib/screener-results';

// Sin metadata propia la pestaña heredaba el título genérico de la app y
// todos los filtros guardados se llamaban igual (WCAG 2.4.2).
export const metadata: Metadata = {
  title: 'Resultados del filtro guardado',
};

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function SavedScreenResultsPage({ params }: { params: Promise<{ screenId: string }> }) {
  const { screenId } = await params;
  // Un id que no es un entero positivo (/screeners/abc) o un filtro que no
  // existe o no es tuyo (/screeners/999999) es un 404 honesto, no la página
  // genérica de error con «Reintentar» (reintentar nunca lo arregla).
  const id = /^\d+$/.test(screenId) ? Number(screenId) : Number.NaN;
  if (!Number.isSafeInteger(id) || id <= 0) notFound();
  const workspace = await getScreenerWorkspace();
  const screen = workspace.screens.find(item => item.id === id);
  if (!screen) notFound();
  const name = screen.name || 'Filtro guardado';
  const result = await runSavedScreen(id);
  const newMatches = new Set(result.new_match_company_ids ?? []);
  // Explicación honesta del 0 coincidencias: si el filtro no coincide por
  // FALTA DE DATO (p.ej. roic >= wacc sin cobertura de wacc), se dice qué
  // métrica falta y en cuántas empresas; no se inventa el dato que falta.
  // Solo campos de CRITERIOS (el ranking nunca decide pertenencia).
  const missingFreq = new Map<string, number>();
  for (const row of result.results) {
    for (const criterion of row.criteria) {
      for (const field of criterion.missing_fields ?? []) {
        missingFreq.set(field, (missingFreq.get(field) ?? 0) + 1);
      }
    }
  }
  const topMissing = [...missingFreq.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
      <ScreenBreadcrumbName name={name} />
      <header className="border-b border-gray-800 pb-5">
        <Button asChild className="mb-4" size="sm" variant="ghost">
          <Link href="/screeners">
            <ArrowLeft className="h-4 w-4" />Screeners
          </Link>
        </Button>
        <p className="text-sm font-semibold uppercase text-teal-300">Filtro guardado</p>
        <h1 className="mt-1 text-3xl font-bold text-gray-100">{name}</h1>
        <p className="mt-2 text-sm text-gray-400">
          {formatNumber(result.match_count, { maximumFractionDigits: 0 })}{' '}
          {result.match_count === 1 ? 'coincidencia' : 'coincidencias'} en{' '}
          {formatNumber(result.company_count, { maximumFractionDigits: 0 })}{' '}
          {result.company_count === 1 ? 'empresa' : 'empresas'}. Esta ejecución registra el historial de
          coincidencias y emite las alertas de nueva coincidencia configuradas.
        </p>
      </header>
      {result.metrics_without_data && result.metrics_without_data.length > 0 ? (
        <p className="rounded-md border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-200" role="alert">
          Ninguna empresa tiene dato de: {screenMissingFieldsLabel(result.metrics_without_data)}. Revisa el nombre de la métrica; el filtro no puede coincidir con ella.
        </p>
      ) : null}
      {result.match_count === 0 && result.company_count > 0 && topMissing.length > 0 ? (
        <p className="rounded-md border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-200" role="alert">
          Sin coincidencias por falta de dato, no por incumplimiento:{' '}
          {topMissing.map(([field, count]) => screenMissingDataEntry(field, count, result.company_count)).join(', ')}.
          El filtro no inventa el dato que falta.
        </p>
      ) : null}
      <section className="grid gap-3">
        {result.results.filter(row => row.matched).map((row) => (
          <article
            className={`rounded-xl border p-4 ${row.matched ? 'border-teal-900/70 bg-teal-950/10' : 'border-gray-800 bg-surface-1'}`}
            key={row.company_id}
          >
            <div className="flex flex-col gap-3 md:flex-row md:items-center">
              <div>
                <Link className="text-lg font-semibold text-teal-300" href={`/research/${row.ticker}`}>
                  {row.ticker}
                </Link>
                <p className="text-sm text-gray-500">{row.name}</p>
              </div>
              <div className="flex flex-wrap gap-2 md:ml-auto">
                <Badge variant="outline">{row.matched ? t('screener.match') : t('screener.noMatch')}</Badge>
                {newMatches.has(row.company_id) ? <Badge>{t('screener.newMatch')}</Badge> : null}
                {result.ranking_formula ? <Badge variant="outline">
                  {t('screener.rank')}{' '}
                  {formatScreenRank(row.rank_value, result.ranking_formula)}
                </Badge> : null}
                <Badge variant="outline">
                  {t('screener.coverage')}{' '}
                  {formatPercent(row.coverage_percent, { fromRatio: false, digits: 0 })}
                </Badge>
                <Badge variant="outline">
                  {t('screener.confidence')} {formatPercent(Number(row.confidence), { digits: 0 })}
                </Badge>
              </div>
            </div>
            {row.missing_fields.length ? (
              <p className="mt-3 text-sm text-amber-300">
                {t('screener.missing')}: {screenMissingFieldsLabel(row.missing_fields)}
              </p>
            ) : null}
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {row.criteria.map((criterion, index) => (
                <div className="flex flex-wrap items-baseline gap-2 rounded-md border border-gray-800 p-3 text-xs" key={index}>
                  <span className={criterion.passed ? 'text-teal-300' : 'text-red-300'}>
                    {criterion.passed ? 'CUMPLE' : 'NO CUMPLE'}
                  </span>
                  <span className="text-gray-300">
                    {screenCriterionMetricLabel(criterion.left)} {criterion.operator} {formatScreenCriterionRight(criterion.right)}
                  </span>
                </div>
              ))}
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
