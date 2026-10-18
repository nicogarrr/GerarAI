import { quoteObserved } from '@/lib/market/quote-observed';
import type { Metadata } from 'next';
import { getMarketIndicesResult } from '@/lib/actions/market.actions';
import { getSavedScreenerEngines, getScreenerStocksReal } from '@/lib/actions/screener.actions';
import { formatMarketCapUsd, formatNumber, formatPercent, formatPrice, isValidCurrencyCode } from '@/lib/format';
import { etiquetaSector } from '@/lib/labels';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { indicesCardState } from '@/lib/market/indices-card-state';
import { t } from '@/lib/i18n/t';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import Link from 'next/link';
import { RefreshCcw } from 'lucide-react';
import FollowButton from '@/components/screener/FollowButton';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
  title: 'Screener',
  description:
    'Large caps líquidos con precio y market cap reales, filtros guardados del motor de análisis y lectura offline con Finnhub.',
};

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

const sectorEs = (value: string) => etiquetaSector(value);

function screenerMarketCap(value: number): string {
  return value > 0 ? formatMarketCapUsd(value) : 'N/D';
}

// Solo el proveedor confirma la divisa, nunca se infiere del ticker.
function screenerPrice(price: number, currency: string | null | undefined): string {
  return currency === 'USD'
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(price)
    : isValidCurrencyCode(currency)
    ? formatPrice(price, currency)
    : formatNumber(price, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default async function ScreenerPage({ searchParams }: { searchParams?: Promise<{ sector?: string }> }) {
  const sector = sectorEn((await searchParams)?.sector ?? 'Information Technology');
  // Screener (backend) e índices (backend) son independientes: en paralelo
  // en vez de en serie. El flag distingue "backend caído" (reintentar) de
  // "filtro sin resultados" (cambiar de sector).
  const [screenerResult, indicesResult, engineScreens] = await Promise.all([
    getScreenerStocksReal({ sector, limit: 25 }).then(
      (rows) => ({ rows, error: null as unknown }),
      (error: unknown) => ({ rows: [] as Awaited<ReturnType<typeof getScreenerStocksReal>>, error }),
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
  ]);
  const { rows, error: screenerError } = screenerResult;
  const backendDown = screenerError !== null;
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
      ? formatPrice(i.price, 'USD')
      : formatNumber(i.price, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <main id="content" tabIndex={-1} className="mx-auto w-full max-w-full min-w-0 space-y-6 overflow-x-clip p-4 sm:p-6">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold break-words text-gray-100">{t('nav.screener')}</h1>
        <p className="mt-1 text-sm text-gray-400">Large caps líquidos con precio y market cap reales.</p>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar por sector">
        {SECTORES.map((s) => (
          <Button key={s.en} asChild variant={sector === s.en ? 'default' : 'outline'} size="sm" className="min-h-[44px] min-w-[44px] rounded-md px-4">
            <Link href={`/screener?sector=${encodeURIComponent(s.en)}`}>{etiquetaSector(s.en)}</Link>
          </Button>
        ))}
      </div>

      <Card className="min-w-0 border-gray-800">
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base break-words">Motor de análisis</CardTitle>
            {engineScreens.engineDown ? (
              <Badge variant="outline">motor no disponible · Finnhub como fallback offline</Badge>
            ) : (
              <Badge>{engineScreens.screens.length} filtros guardados</Badge>
            )}
            <Button asChild variant="outline" size="sm" className="ml-auto">
              <Link href="/screeners">Abrir screeners</Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {engineScreens.engineDown ? (
            <p className="text-sm text-gray-500">
La tabla muestra precios Finnhub como lectura offline, sin análisis de cobertura.
            </p>
          ) : engineScreens.screens.length === 0 ? (
            <p className="text-sm text-gray-500">
              Motor operativo pero sin filtros guardados.{' '}
              <Link href="/screeners" className="text-teal-300 hover:text-teal-200 hover:underline">
                Crea el primero en Screeners
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

      <div className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="min-w-0 border-gray-800 lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base break-words">Oportunidades — {sectorEs(sector)}</CardTitle>
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
                  Motor de análisis desconectado
                </span>
                <p className="mx-auto mt-4 max-w-md text-sm leading-6 text-gray-400 sm:text-base">
                  No hay datos ahora mismo.
                </p>
                <Button asChild className="mt-4 min-h-[44px] px-6">
                  <Link href={`/screener?sector=${encodeURIComponent(sector)}`}>
                    <RefreshCcw aria-hidden="true" className="h-4 w-4" />
                    Reintentar
                  </Link>
                </Button>
                <p className="mt-4 text-xs text-gray-500">
                  El servidor de GerarAI no ha podido completar la consulta. Reintenta en unos segundos.
                </p>
              </div>
              ) : (
              /* Distinto del anterior: aquí el motor responde y el filtro no tiene
               * coincidencias. No se ofrece "Reintentar" porque repetir la misma
               * consulta daría el mismo vacío: la acción es cambiar de sector. */
              <div className="px-4 py-10 text-center">
                <p className="text-sm text-gray-500 sm:text-base">
                  Sin resultados para {sectorEs(sector)} con este filtro. Prueba con otro sector.
                </p>
              </div>
              )
            ) : (
              <div aria-label="Oportunidades por sector" className="overflow-x-auto" role="region" tabIndex={0}>
                {/*
                  Misma <table> en el DOM en todos los viewports (accesibilidad y
                  tests): en <md las filas se muestran como cards apiladas
                  (display block + etiquetas por celda) y desde md como tabla.
                */}
                <table className="w-full text-sm">
                  <caption className="sr-only">Oportunidades del screener por sector: ticker, nombre, precio, cambio de sesión, market cap y acción de seguir</caption>
                  <thead className="hidden md:table-header-group">
                    <tr className="border-b border-gray-800 text-left text-gray-400">
                      <th className="pb-3 pr-4" scope="col">Ticker</th>
                      <th className="pb-3 pr-4" scope="col">Nombre</th>
                      <th className="pb-3 pr-4 text-right" scope="col">Precio</th>
                      <th className="pb-3 pr-4 text-right" scope="col">Cambio sesión</th>
                      <th className="pb-3 pr-4 text-right" scope="col">Market Cap</th>
                      <th className="pb-3 text-right" scope="col">Seguir</th>
                    </tr>
                  </thead>
                  <tbody className="block space-y-3 md:table-row-group md:space-y-0">
                    {rows.map((r) => (
                      <tr key={r.symbol} className="block rounded-xl border border-gray-800 bg-gray-900/40 p-4 hover:bg-gray-800/30 md:table-row md:rounded-none md:border-0 md:border-b md:border-gray-800/60 md:bg-transparent md:p-0 md:last:border-0">
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4">
                          <span className="text-xs text-gray-500 md:hidden">Ticker</span>
                          <Link
                            href={`/research/${r.symbol}`}
                            prefetch
                            className="inline-flex min-h-[44px] items-center font-semibold text-teal-300 hover:text-teal-200"
                          >
                            {r.symbol}
                          </Link>
                        </td>
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4">
                          <span className="shrink-0 text-xs text-gray-500 md:hidden">Nombre</span>
                          <Link href={`/research/${r.symbol}`} prefetch className="max-w-[180px] truncate text-right text-gray-300 hover:text-teal-200 md:max-w-[220px] md:text-left" title={r.name}>{r.name}</Link>
                        </td>
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4 md:text-right">
                          <span className="text-xs text-gray-500 md:hidden">Precio</span>
                          <div className="text-right">
                            <span className="font-semibold text-gray-200">{screenerPrice(r.price, r.currency)}</span>
                            {!isValidCurrencyCode(r.currency) ? <div className="text-[10px] text-gray-500">Divisa N/D: proveedor sin divisa</div> : null}
                            <div className="text-[10px] text-gray-500">{quoteObserved(r.priceAsOf)}</div>
                          </div>
                        </td>
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4 md:text-right">
                          <span className="text-xs text-gray-500 md:hidden">Cambio sesión</span>
                          <span className={`font-mono ${r.changePercent == null ? 'text-gray-400' : r.changePercent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {r.changePercent == null ? 'N/D' : formatPercent(r.changePercent, { fromRatio: false, digits: 2, signDisplay: 'always' })}
                          </span>
                        </td>
                        <td className="flex items-center justify-between gap-3 py-1 md:table-cell md:py-3 md:pr-4 md:text-right">
                          <span className="text-xs text-gray-500 md:hidden">Market Cap</span>
                          <span className="font-mono text-gray-300">
                            {r.marketCap != null && r.marketCap > 0 ? screenerMarketCap(r.marketCap) : 'N/D'}
                          </span>
                        </td>
                        <td className="mt-2 flex items-center justify-between gap-3 border-t border-gray-800/60 pt-3 md:table-cell md:mt-0 md:border-0 md:py-3 md:pt-3 md:text-right">
                          <span className="text-xs text-gray-500 md:hidden">Seguir</span>
                          <FollowButton symbol={r.symbol} company={r.name} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="min-w-0 border-gray-800">
          <CardHeader>
            <CardTitle className="text-base">Índices y macro</CardTitle>
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
                  Motor de análisis desconectado
                </span>
                <p className="mt-4 text-xs text-gray-500">
                  El servidor de GerarAI no ha podido completar la consulta. Reintenta en unos segundos.
                </p>
                <Button asChild variant="outline" size="sm" className="mt-4 min-h-[44px]">
                  <Link href={`/screener?sector=${encodeURIComponent(sector)}`}>
                    <RefreshCcw aria-hidden="true" className="h-4 w-4" />
                    Reintentar
                  </Link>
                </Button>
              </div>
            ) : (
              <>
                <div className="space-y-3">
                  {validIndices.map((i) => (
                    <div key={i.symbol} className="flex min-w-0 items-center justify-between gap-3">
                      <span className="min-w-0 flex-1 truncate text-gray-300">{i.name}</span>
                      <div className="text-right">
                        <span className="font-semibold text-gray-100">{formatIndexValue(i)}{i.unit === 'index' ? ' ptos.' : ''}</span>
                        <div className="text-[10px] text-gray-500">{quoteObserved(i.priceAsOf)}</div>
                      </div>
                    </div>
                  ))}
                  {validIndices.length === 0 && <p className="text-sm text-gray-500">Sin datos de índices</p>}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}

