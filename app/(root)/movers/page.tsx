import type { Metadata } from 'next';
import Link from 'next/link';
import { TrendingDown, TrendingUp, Activity } from 'lucide-react';

import { getMarketMovers, type MarketMover } from '@/lib/actions/market.actions';
import { NA, formatCompact, formatNumber, formatPercent, formatPrice, formatUserDateTime, isValidCurrencyCode } from '@/lib/format';
import BackendOffline from '@/components/system/BackendOffline';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';
import { TickerContextBadges } from '@/components/common/TickerContextBadges';
import { isBackendUnavailableError } from '@/lib/backend-offline';

export const metadata: Metadata = {
  title: 'Movers',
  description:
    'Mayores subidas y caídas sobre los precios que GerarAI tiene ingeridos, con el origen del dato declarado.',
};

export const dynamic = 'force-dynamic';
export const revalidate = 0;

function formatPct(value: number | null): string {
  // `value == null` y no `!value`: un 0,00 % es un dato, no una ausencia.
  if (value == null) return NA;
  // signDisplay: 'always' imprime el + en es-ES sin concatenarlo a mano
  return formatPercent(value, { fromRatio: false, digits: 2, signDisplay: 'always' });
}

type TickerSets = { portfolioTickers: ReadonlySet<string>; watchlistTickers: ReadonlySet<string> };

function MoversTable({ rows, caption, tickerSets, showVolume = false }: { rows: MarketMover[]; caption: string; tickerSets: TickerSets; showVolume?: boolean }) {
  if (!rows.length) {
    return <p className="text-sm text-gray-500">Sin datos todavía — en cuanto haya precios registrados aparecerán aquí.</p>;
  }
  return (
    <div aria-label={caption} className="scroll-affordance-x overflow-x-auto [contain:layout_paint]" role="region" tabIndex={0}>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="border-b border-gray-800 py-2 pr-2" scope="col">Empresa</th>
            <th className="border-b border-gray-800 px-2 py-2 text-right" scope="col">Precio</th>
            <th className="border-b border-gray-800 px-2 py-2 text-right" scope="col">Cambio</th>
            {showVolume ? <th className="border-b border-gray-800 py-2 pl-2 text-right" scope="col">Volumen</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr className="border-b border-gray-900" key={row.ticker}>
              <th className="py-3 pr-2 text-left text-sm font-normal" scope="row">
                <Link className="font-semibold text-teal-300 hover:text-teal-200" href={`/research/${row.ticker}`}>
                  {row.ticker}
                </Link>
                {row.name && row.name.trim().toUpperCase() !== row.ticker.trim().toUpperCase() ? (
                  <div className="max-w-20 truncate text-xs text-gray-500" title={row.name}>{row.name}</div>
                ) : null}
                <TickerContextBadges
                  portfolioTickers={tickerSets.portfolioTickers}
                  ticker={row.ticker}
                  watchlistTickers={tickerSets.watchlistTickers}
                />
              </th>
              <td className="py-3 px-2 text-right text-gray-300">
                {/* Sin divisa valida el precio se muestra sin simbolo, nunca como USD inventado (regla de lib/format). */}
                  <span className="whitespace-nowrap">{isValidCurrencyCode(row.currency) ? formatPrice(row.price, row.currency) : formatNumber(row.price)}</span>
                {row.date ? (
                  <div className="ml-auto max-w-[7.5rem] text-xs text-gray-500">
                    <span className="whitespace-nowrap">del {row.date}</span>
                    {row.registered_at ? <span className="whitespace-nowrap">{` · ${formatUserDateTime(row.registered_at, { hour: '2-digit', minute: '2-digit' })}`}</span> : null}
                  </div>
                ) : null}
              </td>
              <td className={`py-3 px-2 text-right whitespace-nowrap font-medium ${row.change_pct === null ? 'text-gray-500' : row.change_pct >= 0 ? 'text-teal-300' : 'text-red-400'}`}>
                {formatPct(row.change_pct)}
              </td>
              {showVolume ? <td className="py-3 pl-2 text-right whitespace-nowrap text-gray-400">{row.volume == null ? NA : formatCompact(row.volume, { maximumFractionDigits: 1 })}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function MoversPage() {
  let movers, tickerContext;
  try {
    [movers, tickerContext] = await Promise.all([getMarketMovers(10), getTickerContext()]);
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature="Movers" retryHref="/movers" />;
    }
    throw error;
  }

  const tickerSets = {
    portfolioTickers: new Set(tickerContext.portfolioTickers),
    watchlistTickers: new Set(tickerContext.watchlistTickers),
  };

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
      <header className="border-b border-gray-800 pb-5">
        <p className="text-sm font-semibold uppercase text-teal-300">Mercado</p>
        <h1 className="mt-1 text-3xl font-bold text-gray-100">Movers</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">
          Subidas, bajadas y más activas calculadas con los precios registrados en tu base de datos
          (último cierre frente al anterior).
          {movers.as_of
            ? ` El precio más reciente registrado es del ${movers.as_of}; cada fila declara la fecha de su precio y la hora en que se registró.`
            : ' Aún no hay precios registrados.'}
          {movers.session_date
            ? ` Los rankings usan solo la sesión del ${movers.session_date} frente a la sesión anterior.`
            : ''}
          {movers.excluded_not_comparable
            ? ` ${movers.excluded_not_comparable} ${movers.excluded_not_comparable === 1 ? 'valor queda' : 'valores quedan'} fuera por no tener cierre en esa sesión (datos antiguos).`
            : ''}
        </p>
      </header>

      {movers.universe === 0 ? (
        <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
          <h2 className="font-semibold text-gray-100">Sin movimientos todavía</h2>
          <p className="mt-2 text-sm text-gray-400">
            Esta página se llena sola cuando el refresco de mercado guarde precios.
            Mientras tanto puedes explorar los <Link className="text-teal-300 hover:text-teal-200" href="/screeners">screeners</Link> o
            tu <Link className="text-teal-300 hover:text-teal-200" href="/watchlist">watchlist</Link>.
          </p>
        </section>
      ) : (
        <div className="grid gap-6 xl:grid-cols-3 md:grid-cols-1">
          <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5">
            <div className="mb-4 flex items-center gap-2">
              <TrendingUp aria-hidden="true" className="h-5 w-5 text-teal-300" />
              <h2 className="font-semibold text-gray-100">Subidas</h2>
            </div>
            <MoversTable rows={movers.gainers} caption="Mayores subidas" tickerSets={tickerSets} />
          </section>

          <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5">
            <div className="mb-4 flex items-center gap-2">
              <TrendingDown aria-hidden="true" className="h-5 w-5 text-red-400" />
              <h2 className="font-semibold text-gray-100">Bajadas</h2>
            </div>
            <MoversTable rows={movers.losers} caption="Mayores bajadas" tickerSets={tickerSets} />
          </section>

          <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5">
            <div className="mb-4 flex items-center gap-2">
              <Activity aria-hidden="true" className="h-5 w-5 text-teal-300" />
              <h2 className="font-semibold text-gray-100">Más activas</h2>
            </div>
            <MoversTable rows={movers.most_active} caption="Mayor volumen" tickerSets={tickerSets} showVolume />
          </section>
        </div>
      )}
    </main>
  );
}
