import type { Metadata } from 'next';
import Link from 'next/link';
import { TrendingDown, TrendingUp } from 'lucide-react';

import BackendOffline from '@/components/system/BackendOffline';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getMarketThemes } from '@/lib/actions/market-themes.actions';
import { NA, formatMarketDate, formatPercent } from '@/lib/format';
import {
  coverageLabel,
  isHot,
  parseThemeOrder,
  sortThemes,
  themeMetric,
  themeRank,
  themeTone,
  type MarketTheme,
  type ThemeOrder,
} from '@/lib/market/themes';

export const metadata: Metadata = {
  title: 'Temas',
  description: 'Rentabilidad YTD y 1M de temas de mercado: cestas curadas, media simple, cobertura declarada.',
};

export const dynamic = 'force-dynamic';
export const revalidate = 0;

type PageProps = { searchParams: Promise<{ orden?: string | string[] }> };

const pct = (value: number | null) =>
  value === null ? NA : formatPercent(value, { fromRatio: false, digits: 1, signDisplay: 'always' });

const TONE_CARD = {
  up: 'border-teal-400/25 bg-gradient-to-br from-teal-400/10 to-transparent',
  down: 'border-red-400/25 bg-gradient-to-br from-red-400/10 to-transparent',
  none: 'border-gray-800 bg-gray-900/40',
} as const;
const TONE_TEXT = { up: 'text-teal-300', down: 'text-red-400', none: 'text-gray-500' } as const;

function ThemeCard({ theme, order }: { theme: MarketTheme; order: ThemeOrder }) {
  const main = themeMetric(theme, order);
  const other = order === 'ytd' ? theme.m1 : theme.ytd;
  const tone = themeTone(main.pct);
  const rank = themeRank(theme, order);
  const Arrow = tone === 'down' ? TrendingDown : TrendingUp;
  return (
    <li className={`rounded-xl border ${TONE_CARD[tone]}`}>
      <details className="group">
        <summary className="flex min-h-11 cursor-pointer list-none flex-col gap-3 p-4 [&::-webkit-details-marker]:hidden">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs font-semibold text-gray-500">{rank === null ? NA : `#${rank}`}</p>
            <span className="flex gap-1.5">
              {theme.turn ? (
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${theme.turn === 'sube' ? 'bg-teal-400/15 text-teal-300' : 'bg-red-400/15 text-red-300'}`}
                >
                  {theme.turn === 'sube' ? 'Giro al alza' : 'Giro a la baja'}
                </span>
              ) : null}
              {isHot(theme, order) ? (
                <span className="rounded bg-red-500 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">Caliente</span>
              ) : null}
            </span>
          </div>
          <h2 className="text-sm font-semibold text-gray-100">{theme.name}</h2>
          {main.pct === null ? (
            <p className="text-lg font-semibold text-gray-500">Sin datos suficientes</p>
          ) : (
            <p className={`flex items-center gap-2 text-3xl font-bold tabular-nums ${TONE_TEXT[tone]}`}>
              <Arrow aria-hidden="true" className="h-5 w-5" />
              {pct(main.pct)}
            </p>
          )}
          <div className="flex items-center justify-between border-t border-gray-800 pt-2 text-xs text-gray-500">
            <span>{coverageLabel(main, theme.n_total)}</span>
            <span className={`font-semibold tabular-nums ${TONE_TEXT[themeTone(other.pct)]}`}>
              {order === 'ytd' ? '1M' : 'YTD'}: {pct(other.pct)}
            </span>
          </div>
        </summary>
        <div className="border-t border-gray-800 px-4 pb-4 pt-3">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Valores de {theme.name}</caption>
            <thead className="uppercase text-gray-500">
              <tr>
                <th className="py-1 pr-2 font-medium" scope="col">Valor</th>
                <th className="py-1 px-2 text-right font-medium" scope="col">YTD</th>
                <th className="py-1 pl-2 text-right font-medium" scope="col">1M</th>
              </tr>
            </thead>
            <tbody>
              {theme.constituents.map((row) => (
                <tr className="border-t border-gray-900" key={row.ticker}>
                  <th className="py-1.5 pr-2 font-semibold" scope="row">
                    <Link className="text-teal-300 hover:text-teal-200" href={`/research/${row.ticker}`}>
                      {row.ticker}
                    </Link>
                  </th>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${TONE_TEXT[themeTone(row.ytd)]}`}>{pct(row.ytd)}</td>
                  <td className={`pl-2 py-1.5 text-right tabular-nums ${TONE_TEXT[themeTone(row.m1)]}`}>{pct(row.m1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </li>
  );
}

export default async function TemasPage({ searchParams }: PageProps) {
  const order = parseThemeOrder((await searchParams).orden);
  let data;
  try {
    data = await getMarketThemes();
  } catch (error) {
    if (isBackendUnavailableError(error)) return <BackendOffline feature="Temas" retryHref="/temas" />;
    throw error;
  }

  const themes = sortThemes(data.themes, order);
  const link = (target: ThemeOrder, label: string) => (
    <Link
      aria-current={order === target ? 'page' : undefined}
      className={`inline-flex min-h-11 items-center rounded-lg px-4 text-sm font-medium ${order === target ? 'bg-teal-400/10 text-teal-300' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'}`}
      href={target === 'ytd' ? '/temas' : '/temas?orden=1m'}
    >
      {label}
    </Link>
  );

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold text-gray-100">Temas</h1>
        <nav aria-label="Ordenar temas" className="flex gap-1">
          {link('ytd', 'YTD')}
          {link('1m', '1M')}
        </nav>
      </header>

      {themes.length === 0 ? (
        <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
          <h2 className="font-semibold text-gray-100">Sin datos de mercado ahora mismo</h2>
        </section>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {themes.map((theme) => (
            <ThemeCard key={theme.id} order={order} theme={theme} />
          ))}
        </ul>
      )}

      <footer className="border-t border-gray-800 pt-3 text-xs text-gray-500">
        {data.as_of
          ? `${data.source} · ${data.intraday ? 'intradía' : 'cierre'} del ${formatMarketDate(data.as_of)} · ${data.method}`
          : `${data.source} · sin fecha de datos disponible · ${data.method}`}
        {data.status === 'parcial' ? ' · datos parciales' : ''}
        {data.stale ? ' · recalculando: se muestra la última versión calculada' : ''}
      </footer>
    </main>
  );
}
