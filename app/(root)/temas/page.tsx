import type { Metadata } from 'next';
import Link from 'next/link';
import { TrendingDown, TrendingUp } from 'lucide-react';

import BackendOffline from '@/components/system/BackendOffline';
import { ThemeBrainButton } from './_components/ThemeBrainButton';
import { ThemeOrderToggle } from './_components/ThemeOrderToggle';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getBottlenecks } from '@/lib/actions/bottlenecks.actions';
import { getMarketThemes } from '@/lib/actions/market-themes.actions';
import { getFlowHoldings, getMoneyFlow, getMoneyFlowThemes } from '@/lib/actions/money-flows.actions';
import type { MoneyFlow } from '@/lib/market/flows';
import { ThemeFlow, ThemeFlowUnavailable } from './_components/ThemeFlow';
import { ThemeFundamentals } from './_components/ThemeFundamentals';
import { NA, formatMarketDate, formatPercent } from '@/lib/format';
import {
  constituentContribution,
  constituentWeight,
  coverageLabel,
  parseThemeOrder,
  sortThemes,
  themeBadge,
  themeMetric,
  themeRank,
  themeTone,
  type MarketTheme,
  type ThemeOrder,
} from '@/lib/market/themes';
import { paginateThemes, parseThemePage, themePageHref } from '@/lib/market/theme-pagination';
import { THEME_TO_BOTTLENECK } from '@/lib/market/theme-bottleneck-map';

export const metadata: Metadata = {
  title: 'Temas',
  description: 'Rentabilidad YTD y 1M de temas de mercado: cestas curadas, media simple, cobertura declarada.',
};

export const dynamic = 'force-dynamic';
export const revalidate = 0;

type PageProps = { searchParams: Promise<{ orden?: string | string[]; pagina?: string | string[] }> };

const pct = (value: number | null) =>
  value === null ? NA : formatPercent(value, { fromRatio: false, digits: 1, signDisplay: 'always' });

const TONE_CARD = {
  up: 'border-teal-400/25 bg-gradient-to-br from-teal-400/10 to-transparent',
  down: 'border-red-400/25 bg-gradient-to-br from-red-400/10 to-transparent',
  none: 'border-gray-800 bg-gray-900/40',
} as const;
const TONE_TEXT = { up: 'text-teal-300', down: 'text-red-400', none: 'text-gray-500' } as const;

type FlowHoldings = { portfolio: Set<string>; watchlist: Set<string>; unavailable: boolean };

function ThemeCard({
  theme,
  order,
  flow,
  flowUnavailable,
  holdings,
  detectedBottleneck,
}: {
  theme: MarketTheme;
  order: ThemeOrder;
  flow: MoneyFlow | null;
  flowUnavailable: boolean;
  holdings: FlowHoldings;
  detectedBottleneck: string | null;
}) {
  const main = themeMetric(theme, order);
  const other = order === 'ytd' ? theme.m1 : theme.ytd;
  const tone = themeTone(main.pct);
  const rank = themeRank(theme, order);
  const badge = themeBadge(theme, order);
  const first = order === 'ytd' ? theme.ytd : theme.m1;
  const firstLabel = order === 'ytd' ? 'YTD' : '1M';
  const metrics: string[] = [];
  if (theme.ytd.pct !== null) metrics.push(`YTD ${pct(theme.ytd.pct)}`);
  if (theme.m1.pct !== null) metrics.push(`1M ${pct(theme.m1.pct)}`);
  const brainQuestion = `Analiza el tema ${theme.name}${metrics.length > 0 ? ` (${metrics.join(', ')}, media simple de ${theme.n_total} valores)` : ''}: qué lo está moviendo, qué empresas de la cesta destacan y qué vigilarías.`;
  const rows = [...theme.constituents].sort(
    (x, y) =>
      ((order === 'ytd' ? y.ytd : y.m1) ?? -Infinity) - ((order === 'ytd' ? x.ytd : x.m1) ?? -Infinity),
  );
  const Arrow = tone === 'down' ? TrendingDown : TrendingUp;
  return (
    <li className={`rounded-xl border ${TONE_CARD[tone]}`}>
      <details className="group">
        <summary className="flex min-h-11 cursor-pointer list-none flex-col gap-3 p-4 [&::-webkit-details-marker]:hidden">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs font-semibold text-gray-500">{rank === null ? NA : `#${rank}`}</p>
            {badge ? (
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                  badge.kind === 'turn-up'
                    ? 'bg-teal-400/15 text-teal-300'
                    : badge.kind === 'turn-down'
                      ? 'bg-red-400/15 text-red-300'
                      : 'bg-red-600 text-white'
                }`}
              >
                {badge.label}
              </span>
            ) : null}
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
            <caption className="sr-only">Composición de {theme.name}</caption>
            <thead className="uppercase text-gray-500">
              <tr>
                <th className="py-1 pr-2 font-medium" scope="col">Valor</th>
                <th className="px-2 py-1 text-right font-medium" scope="col">Peso</th>
                <th className="px-2 py-1 text-right font-medium" scope="col">{firstLabel}</th>
                <th className="hidden px-2 py-1 text-right font-medium sm:table-cell" scope="col">Aporta</th>
                <th className="py-1 pl-2 text-right font-medium" scope="col">{order === 'ytd' ? '1M' : 'YTD'}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const v1 = order === 'ytd' ? row.ytd : row.m1;
                const v2 = order === 'ytd' ? row.m1 : row.ytd;
                const weight = constituentWeight(theme, first, v1);
                const contribution = constituentContribution(theme, first, v1);
                return (
                  <tr className="border-t border-gray-900" key={row.ticker}>
                    <th className="py-1.5 pr-2 font-semibold" scope="row">
                      <Link className="-my-1 inline-flex min-h-11 min-w-11 items-center justify-center text-teal-300 hover:text-teal-200" href={`/research/${row.ticker}`}>
                        {row.ticker}
                      </Link>
                      {row.reason ? (
                        <span className="mt-0.5 block max-w-[11rem] text-[11px] font-normal leading-4 text-gray-500">
                          {row.reason}
                        </span>
                      ) : null}
                    </th>
                    <td className="px-2 py-1.5 text-right tabular-nums text-gray-400">
                      {weight === null ? NA : formatPercent(weight, { fromRatio: false, digits: 1 })}
                    </td>
                    <td className={`px-2 py-1.5 text-right tabular-nums ${TONE_TEXT[themeTone(v1)]}`}>{pct(v1)}</td>
                    <td className={`hidden px-2 py-1.5 text-right tabular-nums sm:table-cell ${TONE_TEXT[themeTone(contribution)]}`}>
                      {contribution === null ? NA : formatPercent(contribution, { fromRatio: false, digits: 2, signDisplay: 'always' })}
                    </td>
                    <td className={`pl-2 py-1.5 text-right tabular-nums ${TONE_TEXT[themeTone(v2)]}`}>{pct(v2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <ThemeFundamentals themeId={theme.id} />
          {flow ? (
            <ThemeFlow flow={flow} holdings={holdings} />
          ) : flowUnavailable ? (
            <ThemeFlowUnavailable />
          ) : null}
          <ThemeBrainButton question={brainQuestion} />
          {!holdings.unavailable ? (
            <HoldingsLines constituents={theme.constituents} holdings={holdings} />
          ) : null}
          {detectedBottleneck ? (
            <p className="mt-3 border-t border-gray-800 pt-2 text-xs text-gray-400">
              Cuello de botella detectado:{' '}
              <Link className="text-teal-300 underline hover:text-teal-200" href="/cuellos">
                {detectedBottleneck}
              </Link>
            </p>
          ) : null}
        </div>
      </details>
    </li>
  );
}

function HoldingsLines({
  constituents,
  holdings,
}: {
  constituents: MarketTheme['constituents'];
  holdings: { portfolio: Set<string>; watchlist: Set<string> };
}) {
  const tickers = constituents.map((row) => row.ticker.toUpperCase());
  const held = tickers.filter((ticker) => holdings.portfolio.has(ticker));
  const watched = tickers.filter(
    (ticker) => holdings.watchlist.has(ticker) && !holdings.portfolio.has(ticker),
  );
  if (held.length === 0 && watched.length === 0) return null;
  const line = (label: string, symbols: string[]) => (
    <p className="text-xs text-gray-400">
      {label}:{' '}
      {symbols.map((symbol, index) => (
        <span key={symbol}>
          {index > 0 ? ' · ' : ''}
          <Link className="inline-flex min-h-11 min-w-11 items-center justify-center text-teal-300 hover:text-teal-200" href={`/research/${symbol}`}>
            {symbol}
          </Link>
        </span>
      ))}
    </p>
  );
  return (
    <div className="mt-3 space-y-1 border-t border-gray-800 pt-2">
      {held.length > 0 ? line('En tu cartera', held) : null}
      {watched.length > 0 ? line('En tu lista de seguimiento', watched) : null}
    </div>
  );
}

export default async function TemasPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const order = parseThemeOrder(query.orden);
  const requestedPage = parseThemePage(query.pagina);
  let data;
  try {
    data = await getMarketThemes();
  } catch (error) {
    if (isBackendUnavailableError(error)) return <BackendOffline feature="Temas" retryHref="/temas" />;
    throw error;
  }

  // Cruce con Cuellos de botella: si ese carril falla, la pagina sigue sin el enlace.
  const bottlenecks = await getBottlenecks().catch(() => null);
  const detectedThemes = new Set(
    (bottlenecks?.signals ?? [])
      .filter((signal) => signal.status === 'detectado')
      .map((signal) => signal.theme),
  );

  const sortedThemes = sortThemes(data.themes, order);
  const { items: themes, page, pages } = paginateThemes(sortedThemes, requestedPage);
  // Flujos de dinero por tema: degradan en silencio (la página se pinta igual
  // si el endpoint no existe o el backend no responde); jamás un importe
  // inventado en su lugar.
  const flowIds = await getMoneyFlowThemes();
  const [flowPayloads, holdings] = await Promise.all([
    Promise.all(flowIds.map((item) => getMoneyFlow(item.id))),
    getFlowHoldings(),
  ]);
  const flowsById = new Map<string, MoneyFlow>();
  const failedFlowIds = new Set<string>();
  flowIds.forEach((item, index) => {
    const payload = flowPayloads[index];
    if (payload) {
      flowsById.set(item.id, payload);
    } else {
      // El backend declara el flujo pero no lo entrega (fuente caida, 500,
      // timeout): ausencia con causa -> N/D visible, nunca silencio.
      failedFlowIds.add(item.id);
    }
  });

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold text-gray-100">Temas</h1>
        <ThemeOrderToggle order={order} />
      </header>

      {themes.length === 0 ? (
        <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
          <h2 className="font-semibold text-gray-100">Sin datos de mercado ahora mismo</h2>
        </section>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {themes.map((theme) => {
            const bottleneck = THEME_TO_BOTTLENECK[theme.id];
            return (
              <ThemeCard
                detectedBottleneck={bottleneck && detectedThemes.has(bottleneck) ? bottleneck : null}
                flow={flowsById.get(theme.id) ?? null}
                flowUnavailable={failedFlowIds.has(theme.id)}
                holdings={holdings}
                key={theme.id}
                order={order}
                theme={theme}
              />
            );
          })}
        </ul>
      )}

      {pages > 1 ? (
        <nav aria-label="Paginación de temas" className="flex items-center justify-between gap-2">
          {page > 1 ? (
            <Link className="inline-flex min-h-11 items-center rounded-lg px-4 text-sm font-medium text-teal-300 hover:bg-gray-800" href={themePageHref(order, page - 1)} rel="prev">
              Anterior
            </Link>
          ) : (
            <span aria-disabled="true" className="inline-flex min-h-11 items-center px-4 text-sm text-gray-600">Anterior</span>
          )}
          <p aria-current="page" className="text-sm tabular-nums text-gray-400">Página {page} de {pages}</p>
          {page < pages ? (
            <Link className="inline-flex min-h-11 items-center rounded-lg px-4 text-sm font-medium text-teal-300 hover:bg-gray-800" href={themePageHref(order, page + 1)} rel="next">
              Siguiente
            </Link>
          ) : (
            <span aria-disabled="true" className="inline-flex min-h-11 items-center px-4 text-sm text-gray-600">Siguiente</span>
          )}
        </nav>
      ) : null}

      <footer className="border-t border-gray-800 pt-3 text-xs text-gray-500">
        <p>
          {data.as_of
            ? `${data.source} · ${data.intraday ? 'intradía' : 'cierre'} del ${formatMarketDate(data.as_of)} · ${data.method}`
            : `${data.source} · sin fecha de datos disponible · ${data.method}`}
          {data.status === 'parcial' ? ' · datos parciales' : ''}
          {data.stale ? ' · recalculando: se muestra la última versión calculada' : ''}
        </p>
        <details className="mt-2">
          <summary className="inline-flex min-h-11 cursor-pointer items-center font-semibold text-gray-400">Metodología</summary>
          <ul className="list-disc space-y-1 pl-5 leading-5">
            <li>Cada tema es una cesta curada; su rentabilidad es la media simple (mismo peso) de los valores con dato.</li>
            <li>Las cestas son listas fijas curadas a mano (no hay una fuente gratuita fiable de pertenencia), con sesgo de valores de EE. UU. y de supervivencia: es la cesta de hoy, no la histórica. Algunos valores aparecen en más de una cesta (p. ej. GOOGL en 3), así que los temas no son independientes entre sí.</li>
            <li>Un tema sólo publica una métrica si al menos el 70 % de sus valores tiene dato.</li>
            <li>Caliente: los 3 primeros del orden elegido. Giro: YTD y 1M con signo contrario y 1M relevante; el giro sustituye a Caliente.</li>
            <li>Aporta: peso × rentabilidad del valor, en puntos porcentuales.</li>
          </ul>
        </details>
      </footer>
    </main>
  );
}
