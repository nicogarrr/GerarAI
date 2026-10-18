import type { Metadata } from 'next';
import { formatMarketCapUsd, formatNumber, formatPercent, formatPrice, NA } from '@/lib/format';
import { getWatchlistState, getWatchlistEntryData } from '@/lib/actions/watchlist.actions';
import { Eye, TrendingUp, TrendingDown, ArrowRight } from 'lucide-react';
import Link from 'next/link';
import WatchlistRemoveButton from '@/components/watchlist/WatchlistRemoveButton';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from "@/components/ui/card";
import {
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Watchlist',
    description:
        'Seguimiento detallado de los símbolos que sigues: precio, cambio de sesión, market cap y PER (TTM) de cada uno.',
};

interface WatchlistStock {
    symbol: string;
    name: string;
    currency: string | null;
    price: number | null;
    change: number | null;
    changePercent: number | null;
    marketCap: number | null;
    peRatio: number | null;
    priceKind: 'live' | 'close' | null;
    priceAsOf: string | null;
    metricsNotApplicable: boolean;
    addedAt: Date;
}

const PAGE_SIZE = 20;

export default async function WatchlistPage({
    searchParams,
}: {
    searchParams: Promise<{ page?: string }>;
}) {
    const { items: watchlistItems, unavailable } = await getWatchlistState();

    const { page: pageParam } = await searchParams;
    const requestedPage = /^\d+$/.test(pageParam ?? '') ? Number(pageParam) : 1;
    const totalPages = Math.max(1, Math.ceil(watchlistItems.length / PAGE_SIZE));
    const page = Math.min(totalPages, Math.max(1, Number.isSafeInteger(requestedPage) ? requestedPage : 1));
    const pageItems = watchlistItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

    // Cotizar solo la página visible, no toda la lista.
    const watchlistStocks: WatchlistStock[] = await Promise.all(
        pageItems.map(async (item) => {
            try {
                // Precio y divisa del LISTADO REAL (master), nunca del ticker
                // desnudo: Finnhub free lo resuelve en la línea US (ADR en USD
                // u otro emisor) y contradecía la ficha research (F253/F254).
                const data = await getWatchlistEntryData(item.symbol);
                return {
                    symbol: data.symbol,
                    name: data.name,
                    price: data.price,
                    change: data.change,
                    changePercent: data.changePercent,
                    priceKind: data.priceKind,
                    priceAsOf: data.priceAsOf,
                    metricsNotApplicable: data.metricsNotApplicable,
                    currency: data.currency,
                    marketCap: data.marketCap,
                    peRatio: data.peRatio,
                    addedAt: item.addedAt
                };
            } catch {
                // Fallo de red/proveedor: todo a null para pintar NA ('N/D') + badge «sin datos».
                return {
                    symbol: item.symbol,
                    name: item.symbol,
                    price: null,
                    change: null,
                    changePercent: null,
                    priceKind: null,
                    priceAsOf: null,
                    metricsNotApplicable: false,
                    currency: null,
                    marketCap: null,
                    peRatio: null,
                    addedAt: item.addedAt
                };
            }
        })
    );

    const sortedStocks = [...watchlistStocks].sort((a, b) => Number(a.price === null) - Number(b.price === null));

    // Un único formateador para móvil y desktop: sin dato -> NA ('N/D'),
    // nunca un número interpolado sin guarda.
    const formatPeRatio = (peRatio: number | null) => {
        if (peRatio === null || peRatio === undefined || !Number.isFinite(peRatio)) return NA;
        return `${formatNumber(peRatio, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}x`;
    };

    const formatChangePercent = (changePercent: number | null) => {
        if (changePercent === null || changePercent === undefined || !Number.isFinite(changePercent)) return NA;
        // Finnhub ya manda puntos porcentuales (dp), no ratio.
        return formatPercent(changePercent, { fromRatio: false, digits: 2, signDisplay: 'always' });
    };

    // La divisa la fija el listado real; sin divisa verificada se muestra el
    // número pelado, nunca un «US$» asumido (F253).
    const formatPriceCell = (price: number | null, currency: string | null) =>
        price === null ? NA : currency ? formatPrice(price, currency) : formatNumber(price);

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-full min-w-0 flex-col space-y-6 overflow-x-clip p-4 sm:p-6">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                    <h1 className="flex items-center gap-2 text-2xl font-bold break-words text-gray-100 sm:gap-3 sm:text-3xl">
                        <Eye className="h-7 w-7 shrink-0 text-purple-400 sm:h-8 sm:w-8" aria-hidden="true" />
                        Watchlist
                    </h1>

                </div>
            </div>

            {unavailable ? (
                <Card className="border-amber-900/60 bg-amber-950/20" role="alert" data-testid="watchlist-unavailable">
                    <CardContent className="px-4 py-8 text-center text-sm text-amber-200">
                        No se pudo cargar tu watchlist (servicio no disponible). Esto no significa que
                        esté vacía: recarga la página o inténtalo más tarde.
                    </CardContent>
                </Card>
            ) : watchlistStocks.length === 0 ? (
                <Card className="border-gray-700 bg-gray-800/50">
                    <CardContent className="flex flex-col items-center justify-center px-4 py-12 text-center sm:py-16">
                        <Eye className="mb-4 h-12 w-12 text-gray-600 sm:h-16 sm:w-16" aria-hidden="true" />
                        <h2 className="mb-2 text-lg font-semibold text-gray-300 sm:text-xl">Tu Watchlist está vacía</h2>
                        <p className="mb-6 max-w-md text-sm text-gray-500 sm:text-base">
                            Busca la empresa en la búsqueda universal (o con Ctrl+K desde cualquier pantalla) y
                            pulsa &ldquo;Añadir a Watchlist&rdquo; para monitorizarla aquí.
                        </p>
                        <Link
                            href="/search"
                            className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-teal-400/20 px-5 text-sm text-teal-400 transition-colors hover:text-teal-300"
                        >
                            Ir a buscar acciones
                        </Link>
                    </CardContent>
                </Card>
            ) : (
                <>
                    <nav aria-label="Páginas de watchlist" className="flex flex-wrap items-center justify-between gap-3 text-sm text-gray-400">
                        <span>{watchlistItems.length} empresas · Página {page} de {totalPages}</span>
                        <div className="flex gap-3">
                            {page > 1 ? <Link className="inline-flex min-h-[44px] items-center text-teal-300" href={`/watchlist?page=${page - 1}`}>Anterior</Link> : null}
                            {page < totalPages ? <Link className="inline-flex min-h-[44px] items-center text-teal-300" href={`/watchlist?page=${page + 1}`}>Siguiente</Link> : null}
                        </div>
                    </nav>
                    {/* Móvil (<md): cards apiladas con acciones táctiles ≥44px */}
                    <div className="space-y-3 md:hidden">
                        {sortedStocks.map((stock) => (
                            <article key={stock.symbol} className="min-w-0 rounded-xl border border-gray-700/60 bg-gray-900/60 p-4">
                                <div className="flex min-w-0 items-center gap-3">
                                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-gray-800 text-sm font-bold text-gray-300" aria-hidden="true">
                                        {stock.symbol.slice(0, 2)}
                                    </div>
                                    <div className="min-w-0 flex-1">
                                        <Link
                                            href={`/research/${stock.symbol}`}
                                            prefetch
                                            className="flex min-h-11 items-center truncate text-base font-bold text-gray-200"
                                        >
                                            {stock.symbol}
                                        </Link>
                                        <p className="truncate text-xs text-gray-500" title={stock.name}>
                                            {stock.name}
                                        </p>
                                        {stock.price === null ? (
                                            <Badge variant="outline" className="mt-1 border-gray-700 text-gray-400">
                                                sin datos
                                            </Badge>
                                        ) : null}
                                    </div>
                                    <div className={`flex shrink-0 items-center gap-1 font-mono text-sm ${stock.changePercent === null ? 'text-gray-500' : stock.changePercent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        {stock.changePercent === null ? null : stock.changePercent >= 0 ? <TrendingUp className="h-4 w-4" aria-hidden="true" /> : <TrendingDown className="h-4 w-4" aria-hidden="true" />}
                                        <span>
                                            {formatChangePercent(stock.changePercent)}
                                        </span>
                                    </div>
                                </div>
                                <dl className="mt-3 grid grid-cols-3 gap-2 rounded-lg bg-gray-800/50 px-2 py-3 text-center">
                                    <div className="min-w-0">
                                        <dt className="text-[11px] text-gray-500">Precio</dt>
                                        <dd className="truncate font-mono text-sm font-medium text-gray-200">{formatPriceCell(stock.price, stock.currency)}</dd>
                                        {stock.priceKind === 'close' ? (
                                            <dd className="break-words text-[10px] leading-relaxed text-gray-500">{stock.priceAsOf ? `Cierre ${stock.priceAsOf}` : 'Cierre sin fecha de la fuente'}</dd>
                                        ) : null}
                                    </div>
                                    <div className="min-w-0">
                                        <dt className="text-[11px] text-gray-500">Market Cap</dt>
                                        <dd className="truncate font-mono text-sm text-gray-400" title={stock.marketCap === null && stock.metricsNotApplicable ? 'Sin dato: cotiza fuera de EE. UU. y la fuente no da capitalización ni PER fiables de ese mercado' : undefined}>
                                            {stock.marketCap !== null ? formatMarketCapUsd(stock.marketCap) : NA}
                                        </dd>
                                    </div>
                                    <div className="min-w-0">
                                        <dt className="text-[11px] text-gray-500">PER (TTM)</dt>
                                        <dd className="truncate font-mono text-sm text-gray-300" title={stock.peRatio === null && stock.metricsNotApplicable ? 'Sin dato: cotiza fuera de EE. UU. y la fuente no da capitalización ni PER fiables de ese mercado' : undefined}>{formatPeRatio(stock.peRatio)}</dd>
                                    </div>
                                </dl>
                                <div className="mt-3 flex items-center gap-2">
                                    <Link
                                        href={`/research/${stock.symbol}`}
                                        prefetch
                                        aria-label={`Ver análisis de ${stock.symbol}`}
                                        className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-1.5 rounded-lg bg-gray-800 px-4 text-sm font-medium text-gray-200 transition-colors hover:bg-gray-700 hover:text-white"
                                    >
                                        Ver análisis
                                        <ArrowRight className="h-4 w-4" aria-hidden="true" />
                                    </Link>
                                    <WatchlistRemoveButton symbol={stock.symbol} />
                                </div>
                            </article>
                        ))}
                    </div>

                    {/* Desktop (≥md): tabla completa */}
                    <div className="hidden overflow-hidden rounded-lg border border-gray-700 bg-gray-900/50 md:block">
                        <Table regionLabel="Watchlist: precio, cambio, market cap y PER">
                            <TableCaption className="sr-only">Valoración y métricas de cada símbolo de tu watchlist: precio, cambio de sesión, market cap y PER</TableCaption>
                            <TableHeader className="bg-gray-800/80">
                                <TableRow className="border-gray-700 hover:bg-gray-800/80">
                                    <TableHead className="text-gray-300">Símbolo</TableHead>
                                    <TableHead className="text-right text-gray-300">Precio</TableHead>
                                    <TableHead className="text-right text-gray-300">Cambio sesión</TableHead>
                                    <TableHead className="text-right text-gray-300">Market Cap</TableHead>
                                    <TableHead className="text-right text-gray-300">PER (TTM)</TableHead>

                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {sortedStocks.map((stock) => (
                                    <TableRow key={stock.symbol} className="border-gray-800 transition-colors hover:bg-gray-800/30">
                                        <TableCell>
                                            <Link href={`/research/${stock.symbol}`} prefetch className="group flex items-center gap-3">
                                                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-800 font-bold text-gray-300 transition-colors group-hover:bg-gray-700" aria-hidden="true">
                                                    {stock.symbol.slice(0, 2)}
                                                </div>
                                                <div>
                                                    <div className="flex items-center gap-2 font-bold text-gray-200 transition-colors group-hover:text-blue-400">
                                                        {stock.symbol}
                                                        {stock.price === null ? (
                                                            <Badge variant="outline" className="border-gray-700 font-normal text-gray-400">
                                                                sin datos
                                                            </Badge>
                                                        ) : null}
                                                    </div>
                                                    <div className="max-w-[150px] truncate text-xs text-gray-500" title={stock.name}>
                                                        {stock.name}
                                                    </div>
                                                </div>
                                            </Link>
                                            <details className="relative ml-2 inline-block align-middle">
                                                <summary className="min-h-9 cursor-pointer rounded px-2 py-2 text-xs text-gray-400 hover:text-gray-100" aria-label={`Opciones de ${stock.symbol}`}>Opciones</summary>
                                                <div className="mt-1 min-w-40 rounded-md border border-gray-700 bg-gray-900 p-1 shadow-xl">
                                                    <Link href={`/research/${stock.symbol}`} className="block min-h-10 px-3 py-2 text-xs text-teal-300">Ver análisis</Link>
                                                    <WatchlistRemoveButton symbol={stock.symbol} />
                                                </div>
                                            </details>
                                        </TableCell>
                                        <TableCell className="text-right font-mono font-medium text-gray-200">
                                            {formatPriceCell(stock.price, stock.currency)}
                                            {stock.priceKind === 'close' ? (
                                                <div className="text-[10px] font-normal text-gray-500">{stock.priceAsOf ? `Cierre ${stock.priceAsOf}` : 'Cierre sin fecha de la fuente'}</div>
                                            ) : null}
                                        </TableCell>
                                        <TableCell className="text-right">
                                            {stock.changePercent === null ? (
                                                <span className="font-mono text-gray-500">{NA}</span>
                                            ) : (
                                                <div className={`flex items-center justify-end gap-1 ${stock.changePercent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                                    {stock.changePercent >= 0 ? <TrendingUp aria-hidden="true" className="h-3 w-3" /> : <TrendingDown aria-hidden="true" className="h-3 w-3" />}
                                                    <span className="font-mono">
                                                        {formatChangePercent(stock.changePercent)}
                                                    </span>
                                                </div>
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right font-mono text-gray-400" title={stock.marketCap === null && stock.metricsNotApplicable ? 'Sin dato: cotiza fuera de EE. UU. y la fuente no da capitalización ni PER fiables de ese mercado' : undefined}>
                                            {stock.marketCap !== null ? formatMarketCapUsd(stock.marketCap) : NA}
                                        </TableCell>
                                        <TableCell className="text-right">
                                            {stock.peRatio !== null && stock.peRatio !== undefined && Number.isFinite(stock.peRatio) ? (
                                                // F144: sin semáforo. Los umbrales <15/<25 eran
                                                // arbitrarios y ciegos al sector: pintaban de rojo
                                                // KO 26x o ASML 55x, una recomendación implícita en
                                                // una app de «datos, no recomendaciones». Color
                                                // neutro, como en la vista de tarjetas.
                                                <Badge variant="outline" className="border-gray-700 font-mono text-gray-300">
                                                    {formatPeRatio(stock.peRatio)}
                                                </Badge>
                                            ) : (
                                                <span className="text-gray-500">{NA}</span>
                                            )}
                                        </TableCell>

                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                </>
            )}
        </main>
    );
}

