import ValuationSummaryGrid from '@/components/research/ValuationSummaryGrid';
import { quoteObserved } from '@/lib/market/quote-observed';
import type { Metadata } from 'next';
import { getMarketIndicesResult, getMarketMoversResult } from '@/lib/actions/market.actions';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';
import { MoversTable } from '@/components/market/MoversTable';
import BackendOffline from '@/components/system/BackendOffline';
import { getSavedScreenerEngines, getScreenerStocksRealWithStatus } from '@/lib/actions/screener.actions';
import { formatMarketCapUsd, formatMarketDate, formatNumber, formatPercent, formatPrice, formatUserDateTime, isValidCurrencyCode, naFor } from '@/lib/format';
import { etiquetaSector } from '@/lib/labels';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { indicesCardState } from '@/lib/market/indices-card-state';
import { getFormat, getLocale, getT } from '@/lib/i18n/server';
import type { Locale } from '@/lib/i18n/locale';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { OverflowScrollRegion } from '@/components/ui/overflow-scroll-region';
import Link from 'next/link';
import { RefreshCcw } from 'lucide-react';
import FollowButton from '@/components/screener/FollowButton';
import { getWatchlistState } from '@/lib/actions/watchlist.actions';
import SectorSelect from '@/components/screener/SectorSelect';
import { MarketRegimeVista } from '@/components/market/MarketRegime';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('screener.metaTitle'), description: t('screener.metaDescription') };
}

/** Sectores que el Screener ofrece: etiqueta ES de lib/labels.ts + valor EN
 *  que espera el backend. */
// Nombres GICS exactamente como los sirve el backend: filtrar por un nombre
// distinto (p.ej. 'Technology' en vez de 'Information Technology') devuelve
// 0 filas y el primer pintado salía siempre vacío (F223).
const SECTORES = [
  { en: 'Information Technology' },
  { en: 'Health Care' },
  { en: 'Financials' },
  { en: 'Consumer Discretionary' },
  { en: 'Consumer Staples' },
  { en: 'Energy' },
  { en: 'Communication Services' },
  { en: 'Materials' },
];

const sectorEn = (value: string) =>
  SECTORES.some((s) => s.en === value) ? value : 'Information Technology';

// En inglés el sector va con su nombre GICS original (el valor del backend).
const sectorEs = (value: string, locale: Locale = 'es') => (locale === 'en' ? value : etiquetaSector(value));

function screenerMarketCap(value: number, locale: Locale = 'es'): string {
  return value > 0 ? formatMarketCapUsd(value, undefined, locale) : naFor(locale);
}

// Solo el proveedor confirma la divisa, nunca se infiere del ticker.
function screenerPrice(price: number, currency: string | null | undefined, locale: Locale = 'es'): string {
  return isValidCurrencyCode(currency)
    ? formatPrice(price, currency, {}, undefined, locale)
    : formatNumber(price, { minimumFractionDigits: 2, maximumFractionDigits: 2 }, undefined, locale);
}

const VISTAS = [
  { id: 'empresas', href: '/screener' },
  { id: 'subidas', href: '/screener?vista=subidas' },
  { id: 'bajadas', href: '/screener?vista=bajadas' },
  { id: 'activas', href: '/screener?vista=activas' },
  { id: 'regimen', href: '/screener?vista=regimen' },
] as const;

type Vista = (typeof VISTAS)[number]['id'];

const vistaDe = (value: string | undefined): Vista =>
  VISTAS.some((v) => v.id === value) ? (value as Vista) : 'empresas';

async function VistaTabs({ vista }: { vista: Vista }) {
  const t = await getT();
  const labels: Record<Vista, string> = {
    empresas: t('screener.vistas.empresas'),
    subidas: t('screener.vistas.subidas'),
    bajadas: t('screener.vistas.bajadas'),
    activas: t('screener.vistas.activas'),
    regimen: t('screener.vistas.regimen'),
  };
  return (
    <nav aria-label={t('screener.vistasAria')} className="flex flex-nowrap gap-1.5 overflow-x-auto">
      {VISTAS.map((v) => (
        <Button key={v.id} asChild variant={vista === v.id ? 'default' : 'outline'} size="sm" className="min-h-[36px] shrink-0 rounded-md px-3 text-sm">
          <Link aria-current={vista === v.id ? 'page' : undefined} href={v.href} scroll={false}>{labels[v.id]}</Link>
        </Button>
      ))}
    </nav>
  );
}

async function MoversVista({ vista }: { vista: Exclude<Vista, 'empresas'> }) {
  const t = await getT();
  const locale = await getLocale();
  let moversResult, tickerContext;
  try {
    [moversResult, tickerContext] = await Promise.all([getMarketMoversResult(25), getTickerContext()]);
    if (!moversResult.data) throw moversResult.error;
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature={t('screener.metaTitle')} retryHref={`/screener?vista=${vista}`} />;
    }
    throw error;
  }
  const movers = moversResult.data;
  const tickerSets = {
    portfolioTickers: new Set(tickerContext.portfolioTickers),
    watchlistTickers: new Set(tickerContext.watchlistTickers),
  };
  const rows = vista === 'subidas' ? movers.gainers : vista === 'bajadas' ? movers.losers : movers.most_active;
  const caption = vista === 'subidas' ? t('screener.captionSubidas') : vista === 'bajadas' ? t('screener.captionBajadas') : t('screener.captionActivas');
  return (
    <main id="content" tabIndex={-1} className="mx-auto w-full max-w-full min-w-0 space-y-6 overflow-x-clip">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold break-words text-gray-100">{t('nav.screener')}</h1>
        {movers.session_date ? (
          <p className="mt-1 text-sm text-gray-400">
            {t('screener.sessionLine', { date: formatMarketDate(movers.session_date, undefined, locale) })}
            {movers.last_registered_at
              ? ` ${t('screener.lastData', { datetime: formatUserDateTime(movers.last_registered_at, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }, undefined, locale) })}`
              : ''}
            {movers.excluded_not_comparable
              ? ` ${movers.excluded_not_comparable === 1 ? t('screener.excludedNotComparable.one', { count: movers.excluded_not_comparable }) : t('screener.excludedNotComparable.other', { count: movers.excluded_not_comparable })}`
              : ''}
            {movers.excluded_illiquid
              ? ` ${t('screener.excludedIlliquid', { count: movers.excluded_illiquid })}`
              : ''}
          </p>
        ) : null}
      </div>
      <VistaTabs vista={vista} />
      {movers.universe === 0 ? (
        <p className="text-sm text-gray-500">{t('screener.noMovers')}</p>
      ) : (
        <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-3 sm:p-5">
          <MoversTable rows={rows} caption={caption} tickerSets={tickerSets} showVolume={vista === 'activas'} />
        </section>
      )}
    </main>
  );
}

export default async function ScreenerPage({ searchParams }: { searchParams?: Promise<{ sector?: string; vista?: string }> }) {
  const t = await getT();
  const locale = await getLocale();
  const fmt = await getFormat();
  const params = await searchParams;
  const vista = vistaDe(params?.vista);
  if (vista === 'regimen') {
    return (
      <main id="content" tabIndex={-1} className="mx-auto w-full max-w-full min-w-0 space-y-6 overflow-x-clip">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold break-words text-gray-100">{t('nav.screener')}</h1>
        </div>
        <VistaTabs vista={vista} />
        <MarketRegimeVista />
      </main>
    );
  }
  if (vista !== 'empresas') return <MoversVista vista={vista} />;
  const sector = sectorEn(params?.sector ?? 'Information Technology');
  // Screener (backend) e índices (backend) son independientes: en paralelo
  // en vez de en serie. El flag distingue "backend caído" (reintentar) de
  // "filtro sin resultados" (cambiar de sector).
  const [screenerResult, indicesResult, engineScreens, watchlist] = await Promise.all([
    getScreenerStocksRealWithStatus({ sector, limit: 25 }).then(
      (result) => ({ ...result, error: null as unknown }),
      (error: unknown) => ({
        rows: [] as Awaited<ReturnType<typeof getScreenerStocksRealWithStatus>>['rows'],
        refreshing: false,
        unavailable: false,
        universeSize: null as number | null,
        error,
      }),
    ),
    // Resultado discriminado PROPIO (datos/error): la tarjeta de índices no
    // infiere su estado de la petición vecina (screener). Cada llamada puede
    // fallar de forma independiente (caché, ruta, proveedor).
    getMarketIndicesResult(),
    // Motor de análisis (POST /api/screeners/run ad-hoc y filtros guardados):
    // si cae, la tabla Finnhub de abajo queda como lectura offline.
    getSavedScreenerEngines().then(
      (screens) => ({ screens, engineDown: false }),
      () => ({ screens: [] as Awaited<ReturnType<typeof getSavedScreenerEngines>>, engineDown: true }),
    ),
    getWatchlistState(),
  ]);
  const followed = new Set(watchlist.items.map((item) => item.symbol.trim().toUpperCase()));
  const {
    rows,
    refreshing: screenerRefreshing,
    unavailable: screenerUnavailable,
    universeSize,
    error: screenerError,
  } = screenerResult;
  const backendDown = screenerError !== null || screenerUnavailable;
  // Un indice sin precio real (fallo del proveedor) no se pinta como $0.00.
  const validIndices = indicesResult.data.filter((i) => i.price > 0);
  // «Desconectado» solo lo decide el error PROPIO de índices (5xx o sin red
  // según el helper común, no un 4xx): antes se miraba el fallo del screener,
  // así una ruta caída apagaba la tarjeta de la otra y viceversa. Con la
  // petición de índices completada y la lista vacía, «Sin datos de índices»
  // es la lectura honesta.
  const indicesState = indicesCardState(validIndices.length, indicesResult.error, isBackendUnavailableError);
  // F152: un nivel de índice no es dinero - sin sufijo «US$». Solo las
  // series etiquetadas "usd" (Bitcoin/Oro/Plata) llevan US$; un nivel de
  // índice o una serie sin unidad conocida va como número plano, jamás
  // asumiendo dólares.
  const formatIndexValue = (i: (typeof validIndices)[number]) =>
    i.unit === 'usd'
      ? fmt.formatPrice(i.price, 'USD')
      : fmt.formatNumber(i.price, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <main id="content" tabIndex={-1} className="mx-auto w-full max-w-full min-w-0 space-y-6 overflow-x-clip">
      <div className="flex min-w-0 items-baseline gap-3">
        <h1 className="text-xl font-semibold break-words text-gray-100 sm:text-2xl">{t('nav.screener')}</h1>
        {universeSize ? (
          <span className="text-xs text-gray-500">{t('screener.largeCaps', { count: universeSize })}</span>
        ) : null}
      </div>

      <div aria-label={t('screener.filtersAria')} className="flex min-w-0 flex-col gap-2 rounded-lg border border-gray-800 bg-gray-900/30 p-2 xl:flex-row xl:items-center xl:justify-between">
        <VistaTabs vista={vista} />
        <SectorSelect
          options={SECTORES.map((s) => ({ value: s.en, label: sectorEs(s.en, locale) }))}
          value={sector}
        />
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,0.4fr)]">
        <Card className="min-w-0 border-gray-800">
          <CardHeader>
            <CardTitle as="h2" className="text-base break-words">{t('screener.opportunitiesTitle', { sector: sectorEs(sector, locale) })}</CardTitle>
          </CardHeader>
          <CardContent className="min-w-0 px-3 sm:px-6">
            {rows.length === 0 ? (
              backendDown ? (
              /* Mismo aspecto y mismo reintento que components/system/BackendOffline.tsx
               * (distintivo ámbar + explicación + botón Reintentar), pero en línea:
               * aquí la página sigue teniendo contenido útil (filtros de sector,
               * índices) y sustituir la tabla por un error a pantalla completa
               * tiraría el H1 y el panel del motor. */
              <div className="px-4 py-10 text-center">
                <span className="inline-block rounded-full border border-amber-900/60 bg-amber-950/40 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-300">
                  {t('screener.marketDataUnavailable')}
                </span>
                <p className="mx-auto mt-4 max-w-md text-sm leading-6 text-gray-400 sm:text-base">
                  {t('screener.noDataNow')}
                </p>
                <Button asChild className="mt-4 min-h-[44px] px-6">
                  <Link href={`/screener?sector=${encodeURIComponent(sector)}`}>
                    <RefreshCcw aria-hidden="true" className="h-4 w-4" />
                    {t('common.actions.retry')}
                  </Link>
                </Button>
                <p className="mt-4 text-xs text-gray-500">
                  {t('ui.system.failedDetail')}
                </p>
              </div>
              ) : screenerRefreshing ? (
              /* Carga fría: el motor responde pero aún no tiene precios (refresco
               * en vuelo). No es «filtro sin resultados»: la acción es reintentar
               * en unos segundos, no cambiar de sector. */
              <div className="px-4 py-10 text-center">
                <p className="text-sm text-gray-500 sm:text-base">
                  {t('screener.loadingPrices')}
                </p>
                <Button asChild className="mt-4 min-h-[44px] px-6" variant="outline">
                  <Link href={`/screener?sector=${encodeURIComponent(sector)}`}>
                    <RefreshCcw aria-hidden="true" className="h-4 w-4" />
                    {t('common.actions.retry')}
                  </Link>
                </Button>
              </div>
              ) : (
              /* Distinto del anterior: aquí el motor responde y el filtro no tiene
               * coincidencias. No se ofrece "Reintentar" porque repetir la misma
               * consulta daría el mismo vacío: la acción es cambiar de sector. */
              <div className="px-4 py-10 text-center">
                <p className="text-sm text-gray-500 sm:text-base">
                  {t('screener.noResultsForSector', { sector: sectorEs(sector, locale) })}
                </p>
              </div>
              )
            ) : (
              <OverflowScrollRegion label={t('screener.tableRegionLabel')}>
                {/*
                  Misma <table> en el DOM en todos los viewports (accesibilidad y
                  tests): en <md las filas se muestran como cards apiladas
                  (display block + etiquetas por celda) y desde md como tabla.
                */}
                <table className="w-full text-sm">
                  <caption className="sr-only">{t('screener.tableCaption')}</caption>
                  <thead className="hidden md:table-header-group">
                    <tr className="border-b border-gray-800 text-left text-gray-400">
                      <th className="pb-3 pr-4" scope="col">Ticker</th>
                      <th className="pb-3 pr-4" scope="col">{t('screener.colName')}</th>
                      <th className="pb-3 pr-4 text-right" scope="col">{t('screener.colPrice')}</th>
                      <th className="pb-3 pr-4 text-right" scope="col">{t('screener.colChange')}</th>
                      <th className="pb-3 pr-4 text-right" scope="col">{t('screener.colMarketCap')}</th>
                      <th className="pb-3 text-right" scope="col">{t('screener.colFollow')}</th>
                    </tr>
                  </thead>
                  <tbody className="block space-y-3 md:table-row-group md:space-y-0">
                    {rows.map((r) => (
                      <tr key={r.symbol} className="block rounded-xl border border-gray-800 bg-gray-900/40 p-4 hover:bg-gray-800/30 md:table-row md:rounded-none md:border-0 md:border-b md:border-gray-800/60 md:bg-transparent md:p-0 md:last:border-0">
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4">
                          <span className="text-xs text-gray-500 md:hidden">Ticker</span>
                          <Link
                            href={`/research/${r.symbol}`}
                            className="inline-flex min-h-[44px] items-center font-semibold text-teal-300 hover:text-teal-200"
                          >
                            {r.symbol}
                          </Link>
                        </td>
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4">
                          <span className="shrink-0 text-xs text-gray-500 md:hidden">{t('screener.colName')}</span>
                          <Link href={`/research/${r.symbol}`} className="max-w-[180px] truncate text-right text-gray-300 hover:text-teal-200 md:max-w-[220px] md:text-left" title={r.name}>{r.name}</Link>
                        </td>
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4 md:text-right">
                          <span className="text-xs text-gray-500 md:hidden">{t('screener.colPrice')}</span>
                          <div className="text-right">
                            <span className="font-semibold text-gray-200">{screenerPrice(r.price, r.currency, locale)}</span>
                            {!isValidCurrencyCode(r.currency) ? <div className="text-[10px] text-gray-500">{t('screener.currencyMissing')}</div> : null}
                            <div className="text-[10px] text-gray-500">{r.priceDate ? t('screener.dailyData', { date: formatMarketDate(r.priceDate, undefined, undefined, locale) }) : quoteObserved(r.priceAsOf, r.priceTimestampKind, locale)}</div>
                          </div>
                        </td>
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4 md:text-right">
                          <span className="text-xs text-gray-500 md:hidden">{t('screener.colChange')}</span>
                          <span className={`font-mono ${r.changePercent == null ? 'text-gray-400' : r.changePercent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {r.changePercent == null ? naFor(locale) : formatPercent(r.changePercent, { fromRatio: false, digits: 2, signDisplay: 'always' }, undefined, locale)}
                          </span>
                        </td>
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4 md:text-right">
                          <span className="text-xs text-gray-500 md:hidden">{t('screener.colMarketCap')}</span>
                          <span className="font-mono text-gray-300">
                            {r.marketCap != null && r.marketCap > 0 ? screenerMarketCap(r.marketCap, locale) : naFor(locale)}
                          </span>
                        </td>
                        <td className="mt-2 flex items-center justify-between gap-3 border-t border-gray-800/60 pt-3 md:table-cell md:mt-0 md:border-0 md:py-3 md:pt-3 md:text-right">
                          <span className="text-xs text-gray-500 md:hidden">{t('screener.colFollow')}</span>
                          <div className="min-w-0 [&_button]:h-auto [&_button]:whitespace-normal">
                            <FollowButton symbol={r.symbol} company={r.name} isFollowed={followed.has(r.symbol.trim().toUpperCase())} stateUnknown={watchlist.unavailable} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </OverflowScrollRegion>
            )}
          </CardContent>
        </Card>

        <Card className="min-w-0 border-gray-800">
          <CardHeader>
            <CardTitle className="text-base">{t('screener.indicesTitle')}</CardTitle>
          </CardHeader>
          <CardContent>
            {indicesState === 'unavailable' ? (
              /* Mismo tratamiento que la tabla de arriba, en línea: la página
               * sigue teniendo contenido útil (filtros, motor) y sustituir la
               * tarjeta por un error a pantalla completa tiraría el resto.
               * Solo cuando el servidor NO ha podido completar la consulta: con
               * el servidor operativo y la lista vacía, «Sin datos de índices»
               * es la lectura honesta. */
              <div className="py-6 text-center">
                <span className="inline-block rounded-full border border-amber-900/60 bg-amber-950/40 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-300">
                  {t('screener.indicesUnavailable')}
                </span>
                <p className="mt-4 text-xs text-gray-500">
                  {t('ui.system.failedDetail')}
                </p>
                <Button asChild variant="outline" size="sm" className="mt-4 min-h-[44px]">
                  <Link href={`/screener?sector=${encodeURIComponent(sector)}`}>
                    <RefreshCcw aria-hidden="true" className="h-4 w-4" />
                    {t('common.actions.retry')}
                  </Link>
                </Button>
              </div>
            ) : (
              <>
                <div className="space-y-3">
                  {validIndices.map((i) => (
                    <div key={i.symbol} className="min-w-0 space-y-1 border-b border-gray-800 pb-3 last:border-0 last:pb-0">
                      <span className="block text-sm leading-5 text-gray-300">{i.name}</span>
                      <div className="text-right">
                        <span className="font-semibold text-gray-100">{formatIndexValue(i)}{i.unit === 'index' ? ` ${t('screener.indexPoints')}` : ''}</span>
                      </div>
                      <div className="text-right text-[10px] text-gray-500">{quoteObserved(i.priceAsOf, 'daily_candle_open', locale)}</div>
                    </div>
                  ))}
                  {validIndices.length === 0 && <p className="text-sm text-gray-500">{t('screener.noIndices')}</p>}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
      <Card className="min-w-0 border-gray-800">
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base break-words">{t('screener.engineTitle')}</CardTitle>
            {engineScreens.engineDown ? (
              <Badge variant="outline">{t('screener.engineDownBadge')}</Badge>
            ) : engineScreens.screens.length === 0 ? (
              <Badge variant="outline">{t('screener.noSavedFiltersBadge')}</Badge>
            ) : (
              <Badge>{engineScreens.screens.length === 1 ? t('screener.savedFilters.one', { count: 1 }) : t('screener.savedFilters.other', { count: engineScreens.screens.length })}</Badge>
            )}
            <Button asChild variant="outline" size="sm" className="ml-auto">
              <Link href="/screeners">{t('screener.openScreeners')}</Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {engineScreens.engineDown ? (
            <p className="text-sm text-gray-500">
              {t('screener.engineDownText')}
            </p>
          ) : engineScreens.screens.length === 0 ? (
            <p className="text-sm text-gray-500">
              {t('screener.noSavedFiltersText')}{' '}
              <Link href="/screeners" className="text-teal-300 underline underline-offset-2 hover:text-teal-200">
                {t('screener.createFirstLink')}
              </Link>.
            </p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {engineScreens.screens.slice(0, 6).map((screen) => (
                <li key={screen.id}>
                  <Button asChild variant="outline" size="sm">
                    <Link href={`/screeners/${screen.id}`}>{screen.name}</Link>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>


    <ValuationSummaryGrid quotes={rows.map(s => ({ symbol: s.symbol, price: s.price, currency: s.currency ?? null }))} />
    </main>
  );
}
