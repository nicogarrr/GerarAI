import Link from 'next/link';

import type { MarketMover } from '@/lib/actions/market.actions';
import { isValidCurrencyCode } from '@/lib/format';
import { getFormat, getT } from '@/lib/i18n/server';
import { TickerContextBadges } from '@/components/common/TickerContextBadges';

export type TickerSets = { portfolioTickers: ReadonlySet<string>; watchlistTickers: ReadonlySet<string> };

export async function MoversTable({ rows, caption, tickerSets, showVolume = false }: { rows: MarketMover[]; caption: string; tickerSets: TickerSets; showVolume?: boolean }) {
  const t = await getT();
  // Cifras y fechas con el formato del idioma elegido (Ajustes → Idioma).
  const { formatCompact, formatMarketDate, formatNumber, formatPercent, formatPrice, formatUserDateTime, na: NA } = await getFormat();
  const formatPct = (value: number | null): string => {
    // `value == null` y no `!value`: un 0,00 % es un dato, no una ausencia.
    if (value == null) return NA;
    // signDisplay: 'always' imprime el + en es-ES sin concatenarlo a mano
    return formatPercent(value, { fromRatio: false, digits: 2, signDisplay: 'always' });
  };
  if (!rows.length) {
    return <p className="text-sm text-gray-500">{t('movers.table.empty')}</p>;
  }
  return (
    <div aria-label={caption} className="scroll-affordance-x overflow-x-auto [contain:layout_paint]" role="region" tabIndex={0}>
      <table className="w-full text-left text-xs sm:text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="border-b border-gray-800 py-2 pr-2" scope="col">{t('movers.table.company')}</th>
            <th className="border-b border-gray-800 px-2 py-2 text-right" scope="col">{t('movers.table.price')}</th>
            <th className="border-b border-gray-800 px-2 py-2 text-right" scope="col">{t('movers.table.change')}</th>
            {showVolume ? <th className="hidden border-b border-gray-800 py-2 pl-2 text-right sm:table-cell" scope="col">{t('movers.table.volume')}</th> : null}
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
                {showVolume ? <div className="mt-1 text-[10px] text-gray-500 sm:hidden">{t('movers.table.volShort')} {row.volume == null ? NA : formatCompact(row.volume, { maximumFractionDigits: 1 })}</div> : null}
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
                    <span className="whitespace-nowrap">{t('movers.table.dateOf', { date: formatMarketDate(row.date) })}</span>
                    {row.registered_at ? <span className="block whitespace-nowrap">{t('movers.table.registered', { datetime: formatUserDateTime(row.registered_at, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }) })}</span> : null}
                  </div>
                ) : null}
              </td>
              <td className={`py-3 px-2 text-right whitespace-nowrap font-medium ${row.change_pct === null ? 'text-gray-500' : row.change_pct >= 0 ? 'text-good' : 'text-bad'}`}>
                {formatPct(row.change_pct)}
              </td>
              {showVolume ? <td className="hidden py-3 pl-2 text-right whitespace-nowrap text-gray-400 sm:table-cell">{row.volume == null ? NA : formatCompact(row.volume, { maximumFractionDigits: 1 })}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
