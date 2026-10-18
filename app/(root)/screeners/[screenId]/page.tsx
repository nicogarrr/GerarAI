import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScreenBreadcrumbName } from '@/components/screeners/ScreenBreadcrumbName';
import { getScreenerWorkspace, runSavedScreen } from '@/lib/actions/research-tools.actions';
import { formatNumber, formatPercent } from '@/lib/format';
import { t } from '@/lib/i18n/t';
import { formatScreenRank } from '@/lib/screener-results';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function SavedScreenResultsPage({ params }: { params: Promise<{ screenId: string }> }) {
  const { screenId } = await params;
  const workspace = await getScreenerWorkspace();
  const name = workspace.screens.find(screen => screen.id === Number(screenId))?.name ?? 'Filtro guardado';
  const result = await runSavedScreen(Number(screenId));
  const newMatches = new Set(result.new_match_company_ids ?? []);
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
                <Badge variant="outline">
                  {t('screener.rank')}{' '}
                  {formatScreenRank(row.rank_value, result.ranking_formula)}
                </Badge>
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
                {t('screener.missing')}: {row.missing_fields.join(', ')}
              </p>
            ) : null}
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {row.criteria.map((criterion, index) => (
                <div className="rounded-md border border-gray-800 p-3 text-xs" key={index}>
                  <span className={criterion.passed ? 'text-teal-300' : 'text-red-300'}>
                    {criterion.passed ? 'CUMPLE' : 'NO CUMPLE'}
                  </span>
                  <span className="ml-2 text-gray-300">
                    {criterion.left} {criterion.operator} {criterion.right}
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
