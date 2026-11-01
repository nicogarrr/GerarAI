import { Suspense } from 'react';
import type { Metadata } from 'next';
import Link from 'next/link';
import { TrendingDown, TrendingUp } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';

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
import type { Formatters } from '@/lib/format';
import { getFormat, getT } from '@/lib/i18n/server';
import type { TranslateFn } from '@/lib/i18n/translate';
import {
  constituentContribution,
  constituentWeight,
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

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('themes.page.metaTitle'), description: t('themes.page.metaDescription') };
}

export const dynamic = 'force-dynamic';
export const revalidate = 0;

type PageProps = { searchParams: Promise<{ orden?: string | string[]; pagina?: string | string[] }> };

const pctWith = (fmt: Formatters) => (value: number | null) =>
  value === null ? fmt.na : fmt.formatPercent(value, { fromRatio: false, digits: 1, signDisplay: 'always' });

const BADGE_LABELS = {
  'turn-up': 'themes.page.badge.turnUp',
  'turn-down': 'themes.page.badge.turnDown',
  hot: 'themes.page.badge.hot',
} as const;

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
  t,
  fmt,
}: {
  t: TranslateFn;
  fmt: Formatters;
  theme: MarketTheme;
  order: ThemeOrder;
  flow: MoneyFlow | null;
  flowUnavailable: boolean;
  holdings: FlowHoldings;
  detectedBottleneck: string | null;
}) {
  const pct = pctWith(fmt);
  const NA = fmt.na;
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
  const brainQuestion = t('themes.page.brainQuestion', {
    name: theme.name,
    metrics: metrics.length > 0 ? t('themes.page.brainMetrics', { metrics: metrics.join(', '), n: theme.n_total }) : '',
  });
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
                {t(BADGE_LABELS[badge.kind])}
              </span>
            ) : null}
          </div>
          <h2 className="text-sm font-semibold text-gray-100">{theme.name}</h2>
          {main.pct === null ? (
            <p className="text-lg font-semibold text-gray-500">{t('themes.page.notEnoughData')}</p>
          ) : (
            <p className={`flex items-center gap-2 text-3xl font-bold tabular-nums ${TONE_TEXT[tone]}`}>
              <Arrow aria-hidden="true" className="h-5 w-5" />
              {pct(main.pct)}
            </p>
          )}
          <div className="flex items-center justify-between border-t border-gray-800 pt-2 text-xs text-gray-500">
            <span>{t('themes.page.coverage', { n: main.n, total: theme.n_total })}</span>
            <span className={`font-semibold tabular-nums ${TONE_TEXT[themeTone(other.pct)]}`}>
              {order === 'ytd' ? '1M' : 'YTD'}: {pct(other.pct)}
            </span>
          </div>
        </summary>
        <div className="border-t border-gray-800 px-4 pb-4 pt-3">
          {/* La tarjeta mide ~315 px en la rejilla de 2-3 columnas: «Aporta» sale
              sólo si cabe en la tarjeta (container query, no ancho de ventana) y la
              tabla nunca se sale de la tarjeta ni pisa la vecina. */}
          <div className="@container overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">{t('themes.page.composition', { name: theme.name })}</caption>
              <thead className="uppercase text-gray-500">
                <tr>
                  <th className="py-1 pr-2 font-medium" scope="col">{t('themes.page.col.stock')}</th>
                  <th className="px-2 py-1 text-right font-medium" scope="col">{t('themes.page.col.weight')}</th>
                  <th className="px-2 py-1 text-right font-medium" scope="col">{firstLabel}</th>
                  <th className="hidden px-2 py-1 text-right font-medium @sm:table-cell" scope="col">{t('themes.page.col.contributes')}</th>
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
                        {weight === null ? NA : fmt.formatPercent(weight, { fromRatio: false, digits: 1 })}
                      </td>
                      <td className={`px-2 py-1.5 text-right tabular-nums ${TONE_TEXT[themeTone(v1)]}`}>{pct(v1)}</td>
                      <td className={`hidden px-2 py-1.5 text-right tabular-nums @sm:table-cell ${TONE_TEXT[themeTone(contribution)]}`}>
                        {contribution === null ? NA : fmt.formatPercent(contribution, { fromRatio: false, digits: 2, signDisplay: 'always' })}
                      </td>
                      <td className={`pl-2 py-1.5 text-right tabular-nums ${TONE_TEXT[themeTone(v2)]}`}>{pct(v2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <ThemeFundamentals themeId={theme.id} />
          {flow ? (
            <ThemeFlow flow={flow} holdings={holdings} />
          ) : flowUnavailable ? (
            <ThemeFlowUnavailable />
          ) : null}
          <ThemeBrainButton question={brainQuestion} />
          {!holdings.unavailable ? (
            <HoldingsLines constituents={theme.constituents} holdings={holdings} t={t} />
          ) : null}
          {detectedBottleneck ? (
            <p className="mt-3 border-t border-gray-800 pt-2 text-xs text-gray-400">
              {t('themes.page.bottleneck')}{' '}
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
  t,
}: {
  constituents: MarketTheme['constituents'];
  holdings: { portfolio: Set<string>; watchlist: Set<string> };
  t: TranslateFn;
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
      {held.length > 0 ? line(t('themes.page.inPortfolio'), held) : null}
      {watched.length > 0 ? line(t('themes.page.inWatchlist'), watched) : null}
    </div>
  );
}


function TemasBodySkeleton() {
  return (
    <>
      <ul aria-hidden="true" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <li className="rounded-xl border border-gray-800 bg-surface-1 p-5" key={i}>
            <Skeleton className="h-5 w-32" />
            <Skeleton className="mt-3 h-8 w-24" />
            <Skeleton className="mt-3 h-4 w-full" />
          </li>
        ))}
      </ul>
      <Skeleton aria-hidden="true" className="h-4 w-2/3" />
    </>
  );
}

type TemasBodyProps = { order: ReturnType<typeof parseThemeOrder>; requestedPage: number };

async function TemasBody({ order, requestedPage }: TemasBodyProps) {
  const [t, fmt] = await Promise.all([getT(), getFormat()]);
  // Todas las peticiones independientes se disparan a la vez (antes eran
  // secuenciales: cada una esperaba a la anterior; LCP medido 7,3 s en prod).
  const themesPromise = getMarketThemes();
  const bottlenecksPromise = getBottlenecks().catch(() => null);
  const flowIdsPromise = getMoneyFlowThemes();
  const holdingsPromise = getFlowHoldings();
  let data;
  try {
    data = await themesPromise;
  } catch (error) {
    if (isBackendUnavailableError(error)) return <BackendOffline feature={t('themes.page.feature')} retryHref="/temas" />;
    throw error;
  }

  // Cruce con Cuellos de botella: si ese carril falla, la pagina sigue sin el enlace.
  const bottlenecks = await bottlenecksPromise;
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
  const flowIds = await flowIdsPromise;
  const [flowPayloads, holdings] = await Promise.all([
    Promise.all(flowIds.map((item) => getMoneyFlow(item.id))),
    holdingsPromise,
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
    <>
    {themes.length === 0 ? (
        <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
          <h2 className="font-semibold text-gray-100">{t('themes.page.noMarketData')}</h2>
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
                t={t}
                fmt={fmt}
              />
            );
          })}
        </ul>
      )}

      {pages > 1 ? (
        <nav aria-label={t('themes.page.pagerAria')} className="flex items-center justify-between gap-2">
          {page > 1 ? (
            <Link className="inline-flex min-h-11 items-center rounded-lg px-4 text-sm font-medium text-teal-300 hover:bg-gray-800" href={themePageHref(order, page - 1)} rel="prev">
              {t('themes.page.prev')}
            </Link>
          ) : (
            <span aria-disabled="true" className="inline-flex min-h-11 items-center px-4 text-sm text-gray-600">{t('themes.page.prev')}</span>
          )}
          <p aria-current="page" className="text-sm tabular-nums text-gray-400">{t('themes.page.page', { page, total: pages })}</p>
          {page < pages ? (
            <Link className="inline-flex min-h-11 items-center rounded-lg px-4 text-sm font-medium text-teal-300 hover:bg-gray-800" href={themePageHref(order, page + 1)} rel="next">
              {t('themes.page.next')}
            </Link>
          ) : (
            <span aria-disabled="true" className="inline-flex min-h-11 items-center px-4 text-sm text-gray-600">{t('themes.page.next')}</span>
          )}
        </nav>
      ) : null}

      {/* El proveedor no se pinta: es una etiqueta de fuente y la fuente ya
          viaja en la API. Se conservan la frescura del dato, el metodo y los
          avisos de calidad (parcial / recalculando). */}
      <footer className="border-t border-gray-800 pt-3 text-xs text-gray-500">
        <p>
          {data.as_of
            ? `${t(data.intraday ? 'themes.page.intraday' : 'themes.page.close', { date: fmt.formatMarketDate(data.as_of) })} · ${data.method}`
            : `${t('themes.page.noDate')} · ${data.method}`}
          {data.status === 'parcial' ? t('themes.page.partial') : ''}
          {data.stale ? t('themes.page.stale') : ''}
        </p>
        <details className="mt-2">
          <summary className="inline-flex min-h-11 cursor-pointer items-center font-semibold text-gray-400">{t('themes.page.methodology')}</summary>
          <ul className="list-disc space-y-1 pl-5 leading-5">
            <li>{t('themes.page.method.basket')}</li>
            <li>{t('themes.page.method.fixed')}</li>
            <li>{t('themes.page.method.threshold')}</li>
            <li>{t('themes.page.method.labels')}</li>
            <li>{t('themes.page.method.contributes')}</li>
          </ul>
        </details>
      </footer>
    </>
  );
}
export default async function TemasPage({ searchParams }: PageProps) {

  const query = await searchParams;
  const order = parseThemeOrder(query.orden);
  const requestedPage = parseThemePage(query.pagina);
  const t = await getT();

  // La cabecera pinta en el primer chunk; los datos llegan por streaming
  // (antes el primer byte útil esperaba a temas + cuellos + flujos: LCP
  // medido 7,3 s en prod a 390px, 31-oct-2026).
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold text-gray-100">{t('themes.page.title')}</h1>
        <ThemeOrderToggle order={order} />
      </header>
      <Suspense fallback={<TemasBodySkeleton />}>
        <TemasBody order={order} requestedPage={requestedPage} />
      </Suspense>
    </main>
  );
}
