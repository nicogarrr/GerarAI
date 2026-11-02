import ValuationSummaryGrid from '@/components/research/ValuationSummaryGrid';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { TrackedAnalysisStatus } from '@/components/common/TrackedAnalysisStatus';
import type { TrackedAnalysisStatus as AnalysisStatus } from '@/lib/tracked-analysis-status';
import type { Metadata } from 'next';
import { getFormat, getLocale, getT } from '@/lib/i18n/server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getWatchlistState, getWatchlistEntryData, getWatchlistMonitor, type WatchlistEntryData, type WatchlistMonitorItem } from '@/lib/actions/watchlist.actions';
import { getResearchCompaniesBasics, getResearchCompanyBasics, type ResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';
import { getProfile } from '@/lib/actions/finnhub.actions';
import { isTickerNotFound } from '@/lib/watchlist/lookup-status';
import { fetchDatedChanges } from '@/lib/market/dated-change';
import { Eye, TrendingUp, TrendingDown, ArrowRight } from 'lucide-react';
import Link from 'next/link';
import { WatchlistMembership, WatchlistEntry, WatchlistCount } from '@/components/watchlist/WatchlistMembership';
import WatchlistRemoveButton from '@/components/watchlist/WatchlistRemoveButton';
import WatchlistBuyAction from '@/components/watchlist/WatchlistBuyAction';
import WatchlistAddButton from '@/components/watchlist/WatchlistAddButton';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import { sortWatchlistRows } from '@/lib/watchlist/sort-rows';
import DcaSignalsPanel from '@/components/watchlist/DcaSignalsPanel';
import { getDcaSignals } from '@/lib/actions/dca-signals.actions';
import { getPortfolioFxContext } from '@/lib/actions/portfolio.actions';
import type { DcaSignalItem } from '@/lib/dca/types';
import ExtendedHoursLine from '@/components/common/ExtendedHoursLine';
import AnalystTargetLine from '@/components/common/AnalystTargetLine';
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

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return { title: 'Watchlist', description: t('watchlist.page.metaDescription') };
}

// Los 16 campos de cotización/métricas son los de WatchlistEntryData (la
// acción que los resuelve): la fila los hereda y solo añade lo de vista.
interface WatchlistStock extends WatchlistEntryData {
    analysis?: AnalysisStatus | null;
    monitor: WatchlistMonitorItem | null;
    /** true = la cadena de cotización agotó su presupuesto (3 s): las celdas
        sin dato lo dicen como espera, nunca como fallo de la fuente. */
    timedOut: boolean;
    /** true = fuera del master y el proveedor no conoce el símbolo («No encontrado»). */
    notFound: boolean;
    addedAt: Date;
}

// Página corta (móvil primero): 12 filas por página. Con 20 la lista se
// hacía larga en pantallas pequeñas y cada carga cotizaba más símbolos.
const PAGE_SIZE = 12;

export default async function WatchlistPage({
    searchParams,
}: {
    searchParams: Promise<{ page?: string; sort?: string; dir?: string }>;
}) {
    // Señales DCA (watchlist + cartera) en paralelo con el resto de la página.
    const dcaPromise = getDcaSignals();
    // userId para el alta de «Registrar compra» (misma sesión cacheada por
    // petición que usan las acciones de esta página).
    const { id: userId } = await requireAuthenticatedUser();
    // Idioma elegido en Ajustes: textos y formatos (fechas, números) por locale.
    const [t, locale] = await Promise.all([getT(), getLocale()]);
    const { formatMarketCap, formatMarketDate, formatNumber, formatPercent, formatPrice, na: NA } = await getFormat();
    // A9: tipos de la cartera para convertir el objetivo de analistas de un ADR
    // (USD) a la divisa de la fila, como ya hace Cartera.
    const [{ items: watchlistItems, unavailable }, query, { fxRates, baseCurrency }] = await Promise.all([getWatchlistState(), searchParams, getPortfolioFxContext(userId)]);
    const requestedPage = /^\d+$/.test(query.page ?? '') ? Number(query.page) : 1;
    const totalPages = Math.max(1, Math.ceil(watchlistItems.length / PAGE_SIZE));
    const page = Math.min(totalPages, Math.max(1, Number.isSafeInteger(requestedPage) ? requestedPage : 1));

    // Orden por columna via URL (?sort=…&dir=…): estado persistente y
    // compartible sin JS, cabeceras con aria-sort. Los N/D van SIEMPRE al
    // final, en cualquier dirección: un dato ausente nunca «gana» la
    // ordenación (QA 2026-10-19: no había forma de ordenar la watchlist).
    const SORT_KEYS = ['added', 'symbol', 'price', 'change', 'marketCap', 'pe', 'earnings'] as const;
    type SortKey = (typeof SORT_KEYS)[number];
    const sort: SortKey = (SORT_KEYS as readonly string[]).includes(query.sort ?? '') ? (query.sort as SortKey) : 'added';
    const dir: 'asc' | 'desc' = query.dir === 'asc' ? 'asc' : 'desc';
    const SORT_LABELS: Record<SortKey, string> = {
        added: t('watchlist.page.sort.added'), symbol: t('watchlist.page.sort.symbol'), price: t('watchlist.page.sort.price'), change: t('watchlist.page.sort.change'),
        marketCap: t('watchlist.page.sort.marketCap'), pe: t('watchlist.page.sort.pe'), earnings: t('watchlist.page.sort.earnings'),
    };
    // Ordenar por métrica exige cotizar TODA la lista, no solo la página
    // visible: es una acción explícita del usuario y el coste se asume aquí.
    const metricSort = sort !== 'added' && sort !== 'symbol';
    const orderedItems = sort === 'symbol'
        ? [...watchlistItems].sort((a, b) => (dir === 'asc' ? a.symbol.localeCompare(b.symbol) : b.symbol.localeCompare(a.symbol)))
        : watchlistItems;
    const fetchItems = metricSort ? orderedItems : orderedItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
    const pageItems = fetchItems;
    const pageSymbols = fetchItems.map((item) => item.symbol);

    // Cotizar solo la página visible, no toda la lista. Los cierres datados,
    // el monitor denso (52 sem, próximos resultados, tesis) y la lectura por
    // símbolo son independientes: se lanzan a la vez. Antes iban en cadena
    // (cierres, luego monitor, luego símbolos) y el TTFB sumaba los tres tramos.
    const datedChangesPromise = fetchDatedChanges(pageSymbols);
    const monitorPromise = getWatchlistMonitor(pageSymbols);
    // La línea pre/post-mercado (decorativa) NO se espera en el render:
    // la pide el cliente tras el primer pintado (components/watchlist/
    // ExtendedHoursLine). Antes cada carga en frío pagaba el tope de 700 ms
    // por símbolo aunque el dato sea secundario.
    // Presupuesto por símbolo: en una instancia fría la cadena de cotización
    // (Finnhub con cuota free compartida -> respaldo Yahoo con 5 s de timeout
    // por símbolo) medida en prod estiraba el documento a 7-9 s. Pasado el
    // presupuesto la fila usa el CIERRE DATADO de fetchDatedChanges (misma
    // fuente que Movers y Mercado, etiquetado «Cierre <fecha>», F358), nunca
    // un «sin datos» fabricado ni una espera ilimitada. Las lecturas siguen
    // en vuelo y calientan las cachés para la siguiente carga.
    const ENTRY_DATA_BUDGET_MS = 3000;
    // El master (nombre, bolsa, divisa) en UNA petición agregada al backend,
    // fuera del presupuesto: antes era un GET /api/companies/{ticker} por
    // símbolo y carga (20+ round trips; oleada de 16 medida en prod a ~0,9 s,
    // 2026-10-30). Si el backend aún no sirve el agregado (despliegue
    // escalonado front/back) se mantiene la oleada por símbolo.
    const batchedBasics = await getResearchCompaniesBasics(pageSymbols);
    const basicsPromises = pageItems.map((item) => {
        const symbol = item.symbol.trim().toUpperCase();
        return batchedBasics
            ? Promise.resolve(batchedBasics[symbol] ?? null)
            : getResearchCompanyBasics(symbol);
    });
    const entryPromises = pageItems.map((item, index) => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        const basicsPromise = basicsPromises[index];
        return Promise.race([
            basicsPromise.then((basics) => getWatchlistEntryData(item.symbol, basics)),
            new Promise<null>((resolve) => {
                timer = setTimeout(() => resolve(null), ENTRY_DATA_BUDGET_MS);
            }),
        ]).then(
            (value) => {
                // Sin clearTimeout el temporizador colgado mantiene la
                // instancia serverless despierta tras responder.
                if (timer) clearTimeout(timer);
                return { ok: true as const, value };
            },
            () => {
                if (timer) clearTimeout(timer);
                return { ok: false as const };
            },
        );
    });
    // «No encontrado»: solo para filas fuera del master, con el mismo criterio
    // que la ficha (perfil del proveedor sin nombre propio). Presupuesto
    // propio; si el proveedor tarda o falla, sin etiqueta.
    const notFoundPromises = basicsPromises.map((basicsPromise, index) =>
        basicsPromise
            .then((basics) => {
                if (basics) return false;
                const symbol = pageItems[index].symbol.trim().toUpperCase();
                let timer: ReturnType<typeof setTimeout> | undefined;
                return Promise.race([
                    getProfile(symbol).then((profile) => isTickerNotFound(basics, profile, symbol)),
                    new Promise<boolean>((resolve) => {
                        timer = setTimeout(() => resolve(false), ENTRY_DATA_BUDGET_MS);
                    }),
                ]).finally(() => {
                    if (timer) clearTimeout(timer);
                });
            })
            .catch(() => false),
    );
    const [datedChanges, monitorData, basicsList, notFoundList] = await Promise.all([datedChangesPromise, monitorPromise, Promise.all(basicsPromises), Promise.all(notFoundPromises)]);
    const watchlistStocks: WatchlistStock[] = await Promise.all(
        pageItems.map(async (item, index) => {
            try {
                // Precio y divisa del LISTADO REAL (master), nunca del ticker
                // desnudo: Finnhub free lo resuelve en la línea US (ADR en USD
                // u otro emisor) y contradecía la ficha research (F253/F254).
                const settled = await entryPromises[index];
                if (!settled.ok) throw new Error('watchlist entry failed');
                // null = presupuesto agotado: entrada vacía con priceKind null
                // para que el cierre datado (etiquetado) ocupe la celda, pero
                // CON nombre y divisa del master (un cierre en € no sale en $).
                const timedOut = settled.value === null;
                const basics: ResearchCompanyBasics | null = basicsList[index] ?? null;
                const entry: WatchlistEntryData = settled.value ?? {
                    symbol: item.symbol.trim().toUpperCase(),
                    name: basics?.name || item.symbol,
                    exchange: basics?.exchange || null,
                    currency: basics?.currency || null,
                    price: null,
                    change: null,
                    changePercent: null,
                    marketCap: null,
                    marketCapDerived: false,
                    peRatio: null,
                    peKind: null,
                    peSource: null,
                    peSourceLabel: null,
                    priceKind: null,
                    priceAsOf: null,
                    quoteSymbol: null,
                    metricsNotApplicable: false,
                };
                // Mismo cierre datado y mismo % que Movers y Mercado.
                const dated = entry.priceKind === 'live' ? undefined : datedChanges[item.symbol.trim().toUpperCase()];
                const data = dated
                    ? {
                          ...entry,
                          price: dated.price,
                          change: dated.change,
                          changePercent: dated.changePercent,
                          priceKind: 'close' as const,
                          priceAsOf: dated.date,
                      }
                    : entry;
                return {
                    symbol: data.symbol,
                    name: data.name,
                    exchange: data.exchange,
                    price: data.price,
                    change: data.change,
                    changePercent: data.changePercent,
                    priceKind: data.priceKind,
                    priceAsOf: data.priceAsOf,
                    metricsNotApplicable: data.metricsNotApplicable,
                    currency: data.currency,
                    marketCap: data.marketCap,
                    marketCapDerived: data.marketCapDerived,
                    peRatio: data.peRatio,
                    peKind: data.peKind,
                    peSource: data.peSource,
                    peSourceLabel: data.peSourceLabel,
                    quoteSymbol: data.quoteSymbol,
                    analysis: item.analysis,
                    monitor: monitorData.items[item.symbol.trim().toUpperCase()] ?? null,
                    timedOut,
                    notFound: notFoundList[index] === true && data.price === null,
                    addedAt: item.addedAt
                };
            } catch {
                // Fallo de red/proveedor: todo a null para pintar NA ('N/D') + badge «sin datos».
                return {
                    symbol: item.symbol,
                    name: item.symbol,
                    exchange: null,
                    price: null,
                    change: null,
                    changePercent: null,
                    priceKind: null,
                    priceAsOf: null,
                    metricsNotApplicable: false,
                    currency: null,
                    marketCap: null,
                    marketCapDerived: false,
                    peRatio: null,
                    peKind: null,
                    peSource: null,
                    peSourceLabel: null,
                    quoteSymbol: null,
                    analysis: item.analysis,
                    monitor: null,
                    timedOut: false,
                    notFound: notFoundList[index] === true,
                    addedAt: item.addedAt
                };
            }
        })
    );

    const metricValue = (stock: WatchlistStock): number | string | null => {
        switch (sort) {
            case 'price': return stock.price;
            case 'change': return stock.changePercent;
            case 'marketCap': return stock.marketCap;
            case 'pe': return stock.peRatio;
            case 'earnings': return stock.monitor?.next_earnings_date ?? null;
            default: return null;
        }
    };
    const sortedStocks = sortWatchlistRows(watchlistStocks, sort, dir, metricValue);
    const displayStocks = metricSort ? sortedStocks.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) : sortedStocks;

    // Capitalización N/D: una sola leyenda por página en vez de repetir el motivo en cada tarjeta/fila.
    const marketCapGaps = (['timedOut', 'notApplicable', 'unverifiable'] as const)
        .map((reason) => ({
            reason,
            symbols: displayStocks
                .filter((st) => st.marketCap === null && (reason === 'timedOut' ? st.timedOut : reason === 'notApplicable' ? !st.timedOut && st.metricsNotApplicable : !st.timedOut && !st.metricsNotApplicable))
                .map((st) => st.symbol),
        }))
        .filter((group) => group.symbols.length > 0);
    const MARKET_CAP_GAP_TEXT = {
        timedOut: t('watchlist.page.capGap.timedOut'),
        notApplicable: t('watchlist.page.capGap.notApplicable'),
        unverifiable: t('watchlist.page.capGap.unverifiable'),
    };
    const marketCapLegend = marketCapGaps.length > 0 ? (
        <div className="space-y-0.5 text-[11px] leading-relaxed text-gray-500" data-testid="watchlist-marketcap-legend">
            {marketCapGaps.map((group) => (
                <p key={group.reason}>{t('watchlist.page.capLegend', { who: group.symbols.length === displayStocks.length ? t('watchlist.page.capLegendAll') : group.symbols.join(', '), reason: MARKET_CAP_GAP_TEXT[group.reason] })}</p>
            ))}
        </div>
    ) : null;

    const sortHref = (key: SortKey) => {
        if (key === 'added') return '/watchlist';
        const nextDir = sort === key ? (dir === 'asc' ? 'desc' : 'asc') : key === 'symbol' ? 'asc' : 'desc';
        return `/watchlist?sort=${key}&dir=${nextDir}`;
    };
    const pageHref = (target: number) => {
        const params = new URLSearchParams();
        if (sort !== 'added') { params.set('sort', sort); params.set('dir', dir); }
        if (target > 1) params.set('page', String(target));
        const qs = params.toString();
        return qs ? `/watchlist?${qs}` : '/watchlist';
    };
    const ariaSortFor = (key: SortKey): 'ascending' | 'descending' | undefined =>
        sort === key ? (dir === 'asc' ? 'ascending' : 'descending') : undefined;
    const sortIndicator = (key: SortKey) =>
        sort === key ? <span aria-hidden="true" className="text-teal-400">{dir === 'asc' ? '▲' : '▼'}</span> : null;
    // Solo cuentan tickers con valor justo ÚNICO (tesis publicada de K o motor,
    // misma cifra que inicio y screener); sin valoración no se juzga caro/barato.
    const undervaluedCount = watchlistStocks.filter((stock) => stock.monitor?.valuation_side === 'infravalorada').length;
    const overvaluedCount = watchlistStocks.filter((stock) => stock.monitor?.valuation_side === 'sobrevalorada').length;
    const judged = watchlistStocks.filter((stock) => stock.monitor?.valuation_side);
    const byThesis = judged.filter((stock) => stock.monitor?.fair_value_source === 'tesis').length;
    const byEngine = judged.length - byThesis;
    const fairValueSourceNote = [
        byThesis > 0 ? t('watchlist.page.fairValue.byThesis', { count: byThesis }) : null,
        byEngine > 0 ? t('watchlist.page.fairValue.byEngine', { count: byEngine }) : null,
    ].filter(Boolean).join(', ');

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
    // Cuando el calendario de resultados (NASDAQ) cae, el backend devuelve
    // earningsStatus != 'ok' y todas las fechas llegan null: un N/D pelado
    // parecería «sin fecha anunciada». Se explica la causa como en el cap.
    const earningsNote = monitorData.earningsStatus === 'unavailable'
        ? t('watchlist.page.earningsUnavailable')
        : monitorData.earningsStatus === 'partial'
          ? t('watchlist.page.earningsPartial')
          : null;
    const formatPriceCell = (price: number | null, currency: string | null) =>
        price === null ? NA : currency ? formatPrice(price, currency) : formatNumber(price);

    const dca = await dcaPromise;
    const dcaBySymbol = new Map<string, DcaSignalItem>((dca.data?.items ?? []).map((item) => [item.symbol.toUpperCase(), item]));
    const dcaSignalMonths = dca.data?.signal_months ?? null;

    return (
        <WatchlistMembership key={watchlistItems.map((item) => item.symbol).sort().join('|')}>
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-full min-w-0 flex-col space-y-6 overflow-x-clip">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                    <h1 className="flex items-center gap-2 text-xl font-bold break-words text-gray-100 sm:text-2xl">
                        <Eye className="h-5 w-5 shrink-0 text-purple-400" aria-hidden="true" />
                        Watchlist
                    </h1>
                    {undervaluedCount + overvaluedCount > 0 ? (
                        <p className="text-xs text-gray-500">
                            {t('watchlist.page.fairValue.summary', { source: fairValueSourceNote, under: undervaluedCount, over: overvaluedCount })}
                        </p>
                    ) : null}
                </div>
                {/* Alta directa desde la página (QA 2026-10-19: antes solo se
                    podía añadir desde la ficha research o el screener). */}
                <WatchlistAddButton followedSymbols={watchlistItems.map((item) => item.symbol)} />
            </div>

            {unavailable ? (
                <Card className="border-amber-900/60 bg-amber-950/20" role="alert" data-testid="watchlist-unavailable">
                    <CardContent className="px-4 py-8 text-center text-sm text-amber-200">
                        {t('watchlist.page.unavailable')}
                    </CardContent>
                </Card>
            ) : watchlistStocks.length === 0 ? (
                <Card className="border-gray-700 bg-gray-800/50">
                    <CardContent className="flex flex-col items-center justify-center px-4 py-12 text-center sm:py-16">
                        <Eye className="mb-4 h-12 w-12 text-gray-500 sm:h-16 sm:w-16" aria-hidden="true" />
                        <h2 className="mb-2 text-lg font-semibold text-gray-300 sm:text-xl">{t('watchlist.page.empty.title')}</h2>
                        <p className="mb-6 max-w-md text-sm text-gray-500 sm:text-base">
                            {t('watchlist.page.empty.body')}
                            {/* El atajo de teclado solo tiene sentido con teclado físico: en móvil se oculta. */}
                            <span className="hidden md:inline"> {t('watchlist.page.empty.shortcut')}</span>
                        </p>
                        <div className="flex flex-wrap items-center justify-center gap-3">
                            <WatchlistAddButton followedSymbols={[]} />
                            <Link
                                href="/search"
                                className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-teal-400/20 px-5 text-sm text-teal-400 transition-colors hover:text-teal-300"
                            >
                                {t('watchlist.page.empty.searchCta')}
                            </Link>
                        </div>
                    </CardContent>
                </Card>
            ) : (
                <>
                    <nav aria-label={t('watchlist.page.pagesNav')} className="flex flex-nowrap items-center justify-between gap-2 text-xs text-gray-400">
                        <WatchlistCount symbols={watchlistItems.map((item) => item.symbol)} page={page} totalPages={totalPages} />
                        {/* Ordenar también sin cabeceras de tabla (móvil/tablet con tarjetas): menú de enlaces, sin JS. */}
                        <details className="relative xl:hidden">
                            <summary className="min-h-[44px] cursor-pointer list-none rounded px-2 py-2 text-xs text-gray-300 hover:text-gray-100">
                                {t('watchlist.page.sortBy')}: {SORT_LABELS[sort]}{sort !== 'added' ? <span aria-hidden="true" className="text-teal-400"> {dir === 'asc' ? '▲' : '▼'}</span> : null}
                            </summary>
                            <div className="absolute z-10 mt-1 min-w-44 rounded-md border border-gray-700 bg-gray-900 p-1 shadow-xl">
                                {SORT_KEYS.map((key) => (
                                    <Link
                                        key={key}
                                        href={sortHref(key)}
                                        aria-current={sort === key ? 'true' : undefined}
                                        className={`flex min-h-11 items-center px-3 py-2 text-xs ${sort === key ? 'text-teal-300' : 'text-gray-300 hover:text-gray-100'}`}
                                    >
                                        {SORT_LABELS[key]}{sort === key && key !== 'added' ? <span aria-hidden="true"> {dir === 'asc' ? '▲' : '▼'}</span> : null}
                                    </Link>
                                ))}
                            </div>
                        </details>
                        <div className="flex gap-3">
                            {page > 1 ? <Link className="inline-flex min-h-[44px] items-center text-teal-300" href={pageHref(page - 1)}>{t('watchlist.page.prev')}</Link> : null}
                            {page < totalPages ? <Link className="inline-flex min-h-[44px] items-center text-teal-300" href={pageHref(page + 1)}>{t('watchlist.page.next')}</Link> : null}
                        </div>
                    </nav>
                    {/* Móvil y tablet (<xl): cards apiladas con acciones táctiles ≥44px.
                        A 820-1280px la tabla de 6 columnas (~805px de mínimo) no cabe
                        en el contenido con el menú lateral y salía cortada con un
                        scroll horizontal sin indicio (QA 2026-10-19, tablet 820px). */}
                    <div className="space-y-3 xl:hidden">
                        {displayStocks.map((stock) => (
                            <WatchlistEntry as="article" symbol={stock.symbol} key={stock.symbol} className="min-w-0 rounded-xl border border-gray-700/60 bg-gray-900/60 p-3">
                                <div className="flex min-w-0 items-center gap-3">
                                    <CompanyLogo ticker={stock.quoteSymbol ?? stock.symbol} name={stock.name} className="size-11 shrink-0 rounded-lg" />
                                    <div className="min-w-0 flex-1">
                                        <Link
                                            href={`/research/${stock.symbol}`}
                                            className="flex min-h-11 items-center truncate text-base font-bold text-gray-200"
                                        >
                                            {stock.symbol}
                                        </Link>
                                        {stock.name.trim().toUpperCase() !== stock.symbol.toUpperCase() ? <p className="truncate text-xs text-gray-500" title={stock.name}>{stock.name}</p> : null}<TrackedAnalysisStatus analysis={stock.analysis} locale={locale} /><DcaLevelBadge item={dcaBySymbol.get(stock.symbol.toUpperCase())} signalMonths={dcaSignalMonths} compact />
                                        {stock.notFound ? (
                                            <Badge variant="outline" className="mt-1 border-amber-800/60 text-amber-300/90" title={t('watchlist.page.notFound.title')}>
                                                {t('watchlist.page.notFound.label')}
                                            </Badge>
                                        ) : stock.price === null ? (
                                            <Badge variant="outline" className="mt-1 border-gray-700 text-gray-400">
                                                {stock.timedOut ? t('watchlist.page.noDataTimedOut') : t('watchlist.page.noData')}
                                            </Badge>
                                        ) : null}
                                    </div>
                                    <div className={`flex shrink-0 items-center gap-1 font-mono text-sm ${stock.changePercent === null ? 'text-gray-500' : stock.changePercent >= 0 ? 'text-good' : 'text-bad'}`}>
                                        {stock.changePercent === null ? null : stock.changePercent >= 0 ? <TrendingUp className="h-4 w-4" aria-hidden="true" /> : <TrendingDown className="h-4 w-4" aria-hidden="true" />}
                                        <span>
                                            {formatChangePercent(stock.changePercent)}
                                        </span>
                                    </div>
                                </div>
                                <dl className="mt-2 grid grid-cols-2 gap-2 rounded-lg bg-gray-800/50 px-2 py-2 text-center">
                                    <div className="col-span-2 min-w-0">
                                        <dt className="text-[11px] text-gray-500">Precio</dt>
                                        <dd className="truncate font-mono text-sm font-medium text-gray-200">{formatPriceCell(stock.price, stock.currency)}</dd>
                                        {stock.priceKind === 'close' ? (
                                            <dd className="break-words text-[10px] leading-relaxed text-gray-500">{stock.priceAsOf ? t('watchlist.page.closeOn', { date: formatMarketDate(stock.priceAsOf) }) : t('watchlist.page.closeUndated')}</dd>
                                        ) : null}
                                        <ExtendedHoursLine symbol={stock.symbol} currency={stock.currency} as="dd" />
                                    </div>
                                    <div className="min-w-0">
                                        <dt className="text-[11px] text-gray-500">{t('watchlist.page.sort.earnings')}</dt>
                                        <dd className="font-mono text-sm text-gray-300">{stock.monitor?.next_earnings_date ? formatMarketDate(stock.monitor.next_earnings_date) : NA}{!stock.monitor?.next_earnings_date && earningsNote ? <span className="mt-1 block font-sans text-[11px] text-gray-500">{earningsNote}</span> : null}</dd>
                                    </div>
                                    <div className="min-w-0">
                                        <dt className="text-[11px] text-gray-500">{t('watchlist.page.sort.marketCap')}</dt>
                                        <dd className="break-words font-mono text-sm text-gray-400" title={stock.marketCap === null && stock.metricsNotApplicable ? t('watchlist.page.noMetricsTitle') : undefined}>
                                            {stock.marketCap !== null ? formatMarketCap(stock.marketCap, stock.currency) : NA}{stock.marketCap !== null && stock.marketCapDerived ? <span className="ml-1 font-sans text-[11px] text-gray-500">· {t('watchlist.page.derived')}</span> : null}{stock.marketCap === null ? <sup aria-hidden="true" className="ml-0.5 font-sans text-[10px] text-gray-500">*</sup> : null}
                                        </dd>
                                    </div>
                                    <div className="min-w-0">
                                        <dt className="text-[11px] text-gray-500">{stock.peKind === 'fy' ? t('watchlist.page.peFy') : t('watchlist.page.peTtm')}</dt>
                                        <dd className="font-mono text-sm text-gray-300" title={stock.peSource ?? (stock.peRatio === null && stock.metricsNotApplicable ? t('watchlist.page.noMetricsTitle') : undefined)}>{formatPeRatio(stock.peRatio)}{stock.peRatio !== null && stock.peSourceLabel ? <span className="ml-1 font-sans text-[11px] text-gray-500">· {stock.peSourceLabel}</span> : null}{stock.peRatio === null ? (stock.timedOut ? <span className="mt-1 block font-sans text-[11px] text-gray-500">{t('watchlist.page.readTimedOut')}</span> : stock.metricsNotApplicable ? <span className="mt-1 block font-sans text-[11px] text-gray-500">{t('watchlist.page.peNotCovered')}</span> : null) : null}</dd>
                                    </div>
                                    <div className="min-w-0">
                                        <dt className="text-[11px] text-gray-500" title={t('watchlist.page.analystTitle')}>{t('watchlist.page.analystTarget')}</dt>
                                        <dd className="text-sm"><AnalystTargetLine symbol={stock.symbol} quoteSymbol={stock.quoteSymbol} currency={stock.currency} referencePrice={stock.price} fxRates={fxRates} baseCurrency={baseCurrency} /></dd>
                                    </div>
                                </dl>
                                <div className="mt-2 flex items-center gap-2">
                                    <Link
                                        href={`/research/${stock.symbol}`}
                                        aria-label={t('watchlist.page.viewAnalysisOf', { symbol: stock.symbol })}
                                        className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-1.5 rounded-lg bg-gray-800 px-4 text-sm font-medium text-gray-200 transition-colors hover:bg-gray-700 hover:text-white"
                                    >
                                        {t('watchlist.page.viewAnalysis')}
                                        <ArrowRight className="h-4 w-4" aria-hidden="true" />
                                    </Link>
                                    <WatchlistBuyAction userId={userId} symbol={stock.symbol} companyName={stock.name} currency={stock.currency} variant="button" />
                                    <WatchlistRemoveButton symbol={stock.symbol} />
                                </div>
                            </WatchlistEntry>
                        ))}
                        {marketCapLegend}
                    </div>

                    {/* Desktop (≥xl): tabla completa */}
                    <div className="hidden overflow-hidden rounded-lg border border-gray-700 bg-gray-900/50 xl:block">
                        <Table regionLabel={t('watchlist.page.tableRegion')}>
                            <TableCaption className="sr-only">{t('watchlist.page.tableCaption')}</TableCaption>
                            <TableHeader className="bg-gray-800/80">
                                <TableRow className="border-gray-700 hover:bg-gray-800/80">
                                    <TableHead className="text-gray-300" aria-sort={ariaSortFor('symbol')}>
                                        <Link href={sortHref('symbol')} className="inline-flex min-h-[44px] items-center gap-1 hover:text-gray-100">{t('watchlist.page.sort.symbol')}{sortIndicator('symbol')}</Link>
                                    </TableHead>
                                    <TableHead className="text-right text-gray-300" aria-sort={ariaSortFor('price')}>
                                        <Link href={sortHref('price')} className="inline-flex min-h-[44px] items-center justify-end gap-1 hover:text-gray-100">{t('watchlist.page.sort.price')}{sortIndicator('price')}</Link>
                                    </TableHead>
                                    <TableHead className="text-right text-gray-300" aria-sort={ariaSortFor('change')}>
                                        <Link href={sortHref('change')} className="inline-flex min-h-[44px] items-center justify-end gap-1 hover:text-gray-100">{t('watchlist.page.sort.change')}{sortIndicator('change')}</Link>
                                    </TableHead>
                                    <TableHead className="text-right text-gray-300" aria-sort={ariaSortFor('marketCap')}>
                                        <Link href={sortHref('marketCap')} className="inline-flex min-h-[44px] items-center justify-end gap-1 hover:text-gray-100">{t('watchlist.page.sort.marketCap')}{sortIndicator('marketCap')}</Link>
                                    </TableHead>
                                    <TableHead className="text-right text-gray-300" aria-sort={ariaSortFor('pe')}>
                                        <Link href={sortHref('pe')} className="inline-flex min-h-[44px] items-center justify-end gap-1 hover:text-gray-100">{t('watchlist.page.sort.pe')}{sortIndicator('pe')}</Link>
                                    </TableHead>
                                    <TableHead className="text-right text-gray-300" title={t('watchlist.page.analystTitle')}>
                                        {t('watchlist.page.analystTarget')}
                                    </TableHead>
                                    <TableHead className="text-right text-gray-300" aria-sort={ariaSortFor('earnings')}>
                                        <Link href={sortHref('earnings')} className="inline-flex min-h-[44px] items-center justify-end gap-1 hover:text-gray-100">{t('watchlist.page.sort.earnings')}{sortIndicator('earnings')}</Link>
                                    </TableHead>

                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {displayStocks.map((stock) => (
                                    <WatchlistEntry as="tr" symbol={stock.symbol} key={stock.symbol} className="border-gray-800 transition-colors hover:bg-gray-800/30">
                                        <TableCell>
                                            <Link href={`/research/${stock.symbol}`} className="group flex items-center gap-3">
                                                <CompanyLogo ticker={stock.quoteSymbol ?? stock.symbol} name={stock.name} className="size-10 shrink-0 rounded-lg" />
                                                <div>
                                                    <div className="flex items-center gap-2 font-bold text-gray-200 transition-colors group-hover:text-blue-400">
                                                        {stock.symbol}
                                                        {stock.notFound ? (
                                                            <Badge variant="outline" className="border-amber-800/60 font-normal text-amber-300/90" title={t('watchlist.page.notFound.title')}>
                                                                {t('watchlist.page.notFound.label')}
                                                            </Badge>
                                                        ) : stock.price === null ? (
                                                            <Badge variant="outline" className="border-gray-700 font-normal text-gray-400">
                                                                {stock.timedOut ? t('watchlist.page.noDataTimedOut') : t('watchlist.page.noData')}
                                                            </Badge>
                                                        ) : null}
                                                        {stock.monitor && stock.price !== null && stock.monitor.low_52w !== null && stock.monitor.low_52w_sessions >= 120 && stock.price <= stock.monitor.low_52w * 1.02 ? (
                                                            <Badge variant="outline" className="border-amber-800/60 font-normal text-amber-300/90" title={t('watchlist.page.low52Title', { price: stock.monitor.currency ? formatPrice(stock.monitor.low_52w, stock.monitor.currency) : formatNumber(stock.monitor.low_52w), sessions: stock.monitor.low_52w_sessions })}>
                                                                {t('watchlist.page.low52')}
                                                            </Badge>
                                                        ) : null}
                                                    </div>
                                                    {stock.name.trim().toUpperCase() !== stock.symbol.toUpperCase() ? <div className="max-w-[150px] truncate text-xs text-gray-500" title={stock.name}>{stock.name}</div> : null}<TrackedAnalysisStatus analysis={stock.analysis} locale={locale} /><DcaLevelBadge item={dcaBySymbol.get(stock.symbol.toUpperCase())} signalMonths={dcaSignalMonths} compact />
                                                </div>
                                            </Link>
                                            <div className="ml-2 flex items-center gap-1">
                                                <details className="relative inline-block align-middle">
                                                    <summary className="min-h-9 cursor-pointer rounded px-2 py-2 text-xs text-gray-400 hover:text-gray-100" aria-label={t('watchlist.page.optionsOf', { symbol: stock.symbol })}>{t('watchlist.page.options')}</summary>
                                                    <div className="mt-1 min-w-40 rounded-md border border-gray-700 bg-gray-900 p-1 shadow-xl">
                                                        <Link href={`/research/${stock.symbol}`} className="flex min-h-11 items-center px-3 py-2 text-xs text-teal-300">{t('watchlist.page.viewAnalysis')}</Link>
                                                        <WatchlistBuyAction userId={userId} symbol={stock.symbol} companyName={stock.name} currency={stock.currency} variant="menu-item" />
                                                    </div>
                                                </details>
                                                {/* Quitar siempre visible (QA 2026-10-19): antes iba dentro de «Opciones» y en escritorio no se descubría; en móvil ya era visible. */}
                                                <WatchlistRemoveButton symbol={stock.symbol} />
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-right font-mono font-medium text-gray-200">
                                            {formatPriceCell(stock.price, stock.currency)}
                                            {stock.priceKind === 'close' ? (
                                                <div className="text-[10px] font-normal text-gray-500">{stock.priceAsOf ? t('watchlist.page.closeOn', { date: formatMarketDate(stock.priceAsOf) }) : t('watchlist.page.closeUndated')}</div>
                                            ) : null}
                                            <ExtendedHoursLine symbol={stock.symbol} currency={stock.currency} />
                                        </TableCell>
                                        <TableCell className="text-right">
                                            {stock.changePercent === null ? (
                                                <span className="font-mono text-gray-500">{NA}</span>
                                            ) : (
                                                <div className={`flex items-center justify-end gap-1 ${stock.changePercent >= 0 ? 'text-good' : 'text-bad'}`}>
                                                    {stock.changePercent >= 0 ? <TrendingUp aria-hidden="true" className="h-3 w-3" /> : <TrendingDown aria-hidden="true" className="h-3 w-3" />}
                                                    <span className="font-mono">
                                                        {formatChangePercent(stock.changePercent)}
                                                    </span>
                                                </div>
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right font-mono text-gray-400" title={stock.marketCap === null && stock.metricsNotApplicable ? t('watchlist.page.noMetricsTitle') : undefined}>
                                            {stock.marketCap !== null ? formatMarketCap(stock.marketCap, stock.currency) : NA}{stock.marketCap !== null && stock.marketCapDerived ? <span className="ml-1 font-sans text-[11px] text-gray-500">· {t('watchlist.page.derived')}</span> : null}{stock.marketCap === null ? <sup aria-hidden="true" className="ml-0.5 font-sans text-[10px] text-gray-500">*</sup> : null}
                                        </TableCell>
                                        <TableCell className="text-right">
                                            {stock.peRatio !== null && stock.peRatio !== undefined && Number.isFinite(stock.peRatio) ? (
                                                // F144: sin semáforo. Los umbrales <15/<25 eran
                                                // arbitrarios y ciegos al sector: pintaban de rojo
                                                // KO 26x o ASML 55x, una recomendación implícita en
                                                // una app de «datos, no recomendaciones». Color
                                                // neutro, como en la vista de tarjetas.
                                                <Badge variant="outline" className="border-gray-700 font-mono text-gray-300" title={stock.peSource ?? undefined}>
                                                    {formatPeRatio(stock.peRatio)}{stock.peRatio !== null && stock.peKind === 'fy' ? <span className="ml-1 font-sans text-[11px] text-gray-500">· FY</span> : null}{stock.peRatio !== null && stock.peSourceLabel ? <span className="ml-1 font-sans text-[11px] text-gray-500">· {stock.peSourceLabel}</span> : null}{stock.peRatio === null ? (stock.timedOut ? <span className="mt-1 block font-sans text-[11px] text-gray-500">{t('watchlist.page.readTimedOut')}</span> : stock.metricsNotApplicable ? <span className="mt-1 block font-sans text-[11px] text-gray-500">{t('watchlist.page.peNotCovered')}</span> : null) : null}
                                                </Badge>
                                            ) : (
                                                <span className="text-gray-500">{NA}</span>
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right text-sm">
                                            <AnalystTargetLine symbol={stock.symbol} quoteSymbol={stock.quoteSymbol} currency={stock.currency} referencePrice={stock.price} fxRates={fxRates} baseCurrency={baseCurrency} />
                                        </TableCell>
                                        <TableCell className="text-right font-mono text-sm text-gray-300" title={stock.monitor?.next_earnings_source ?? (!stock.monitor?.next_earnings_date ? earningsNote ?? undefined : undefined)}>
                                            {stock.monitor?.next_earnings_date ? formatMarketDate(stock.monitor.next_earnings_date) : NA}{!stock.monitor?.next_earnings_date && earningsNote ? <span className="block font-sans text-[11px] text-gray-500">{earningsNote}</span> : null}
                                        </TableCell>

                                    </WatchlistEntry>
                                ))}
                            </TableBody>
                        </Table>
                        {marketCapLegend ? <div className="border-t border-gray-700 px-4 py-2">{marketCapLegend}</div> : null}
                    </div>
                </>
            )}

            <DcaSignalsPanel data={dca.data} unavailable={dca.unavailable} ti={t} locale={locale} />
        <ValuationSummaryGrid quotes={watchlistStocks.map(s => ({ symbol: s.symbol, price: s.price, currency: s.currency }))} />
        </main>
        </WatchlistMembership>
    );
}

