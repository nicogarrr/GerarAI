'use client';

import { formatDate, formatMoney, formatPercent } from '@/lib/format';
import { useState, useMemo } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { useActiveTabVisible } from './use-active-tab-visible';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import dynamic from 'next/dynamic';
import PortfolioDataNotice from '@/components/portfolio/PortfolioDataNotice';
import PortfolioSummary from '@/components/portfolio/PortfolioSummary';
import { hasCostBasis } from '@/lib/portfolio-insight';
import { windowNav } from '@/lib/portfolio-nav';
import AddTransactionButton from '@/components/portfolio/AddTransactionButton';
import PortfolioAllocation from '@/components/portfolio/PortfolioAllocation';
const PortfolioNavChart = dynamic(() => import('./PortfolioNavChart'), {
    ssr: false,
    loading: () => (
        <div className="h-full w-full animate-pulse rounded-lg border border-gray-800 bg-gray-900/40" aria-label="Cargando gráfico" role="status" />
    ),
});
import PortfolioTearsheet from '@/components/portfolio/PortfolioTearsheet';
import RefreshPortfolioButton from '@/components/portfolio/RefreshPortfolioButton';
// Las vistas de cada pestaña secundaria solo se montan al abrirla (los
// TabsContent de Radix no renderizan el panel inactivo), pero con imports
// estáticos su JS viajaba igual en el bundle inicial de /portfolio
// (~28 KB gz entre posiciones, movimientos y previsión). Con dynamic cada
// vista se descarga la primera vez que se abre su pestaña; «Resumen» se queda
// eager (pestaña inicial y LCP). Si la URL entra con ?tab=posiciones (u otra),
// el SSR precarga su chunk, como debe.
const TabFallback = () => (
    <div role="status" aria-label="Cargando la sección" className="mt-0 flex min-h-[200px] items-center justify-center rounded-xl border border-gray-800 bg-gray-900/40">
        <span className="block h-4 w-1/3 animate-pulse rounded bg-gray-700/60" aria-hidden="true" />
    </div>
);

const PortfolioHoldings = dynamic(() => import('@/components/portfolio/PortfolioHoldings'), { loading: TabFallback });
const PortfolioTransactions = dynamic(() => import('@/components/portfolio/PortfolioTransactions'), { loading: TabFallback });
const PortfolioScores = dynamic(() => import('@/components/portfolio/PortfolioScores'), { loading: TabFallback });
const SavingsProjection = dynamic(() => import('@/components/portfolio/SavingsProjection'), { loading: TabFallback });
const PortfolioForecast = dynamic(() => import('@/components/portfolio/PortfolioForecast'), { loading: TabFallback });
const PortfolioDividends = dynamic(() => import('@/components/portfolio/PortfolioDividends'), { loading: TabFallback });

import { Wallet, LayoutDashboard, Briefcase, TrendingUp, TrendingDown, History, Brain, Gauge, Activity, Coins } from 'lucide-react';
import type { PortfolioForecast as PortfolioForecastType, PortfolioPerformanceHistory, PortfolioSummary as PortfolioSummaryType, PortfolioTearsheet as PortfolioTearsheetType, PortfolioDividendProjection } from '@/lib/actions/portfolio.actions';

type Transaction = {
    _id: string;
    symbol: string;
    type: 'buy' | 'sell';
    quantity: number;
    price: number;
    date: string;
    notes?: string;
};

type Props = {
    summary: PortfolioSummaryType;
    transactions: Transaction[];
    transactionPage?: { total: number; offset: number };
    scores: { quality: number | null; growth: number | null; value: number | null; dividend: number | null; cagr3y: number | null; history?: PortfolioPerformanceHistory };
    tearsheet: PortfolioTearsheetType | null;
    forecast: PortfolioForecastType | null;
    dividends: PortfolioDividendProjection | null;
    userId: string;
    partialMessage?: string | null;
};

// F137: la pestaña vive en la URL (?tab=). Antes el estado nacía fijo en
// 'resumen' y el parámetro se ignoraba tras la hidratación: un enlace a
// /portfolio?tab=movimientos aterrizaba siempre en resumen. Un valor
// desconocido cae a resumen sin romper la página.
const VALID_TABS = ['resumen', 'prevision', 'dividendos', 'posiciones', 'movimientos', 'estrategia'] as const;
type PortfolioTab = (typeof VALID_TABS)[number];

// Alias legibles: la pestaña visible se llama "Factores" pero el valor
// interno es "estrategia"; un enlace a ?tab=factores no debe caer a resumen.
const TAB_ALIASES: Record<string, PortfolioTab> = { factores: 'estrategia' };

function normalizeTab(value: string | null): PortfolioTab {
    if (value && value in TAB_ALIASES) return TAB_ALIASES[value];
    return (VALID_TABS as readonly string[]).includes(value ?? '') ? (value as PortfolioTab) : 'resumen';
}

export default function PortfolioTabs({ summary, transactions, transactionPage, scores, tearsheet, forecast, dividends, userId, partialMessage }: Props) {
    const searchParams = useSearchParams();
    const pathname = usePathname();
    const tabParam = searchParams.get('tab');
    const [activeTab, setActiveTab] = useState<PortfolioTab>(() => normalizeTab(tabParam));

    const tabViewportRef = useActiveTabVisible(activeTab);

    // Navegación cliente posterior a la hidratación (atrás/adelante,
    // enlaces con ?tab=): sincroniza el estado con la URL. Se ajusta durante
    // el render al cambiar el parámetro (patrón de React para estado derivado
    // de props) en vez de con un efecto que pinta primero la pestaña vieja.
    const [syncedTabParam, setSyncedTabParam] = useState(tabParam);
    if (tabParam !== syncedTabParam) {
        setSyncedTabParam(tabParam);
        setActiveTab(normalizeTab(tabParam));
    }

    const handleTabChange = (value: string) => {
        const next = normalizeTab(value);
        setActiveTab(next);
        // Preserva los demás query params: replace sobre `${pathname}?tab=`
        // los borraba todos (revisión #456).
        const params = new URLSearchParams(searchParams.toString());
        params.set('tab', next);
        // replaceState nativo en vez de router.replace: el cambio de pestaña
        // es client-side y router.replace esperaba a la navegación RSC, así
        // que la URL enseñaba la pestaña anterior ~1-2 s (reproducido 21-oct):
        // copiar el enlace o recargar en ese rato compartía la pestaña vieja.
        window.history.replaceState(null, '', `${pathname}?${params.toString()}`);
    };
    const [chartPeriod, setChartPeriod] = useState('1M');

    const periodData = useMemo(() => Object.fromEntries(
        ['1S', '1M', '3M', '6M', 'YTD', '1A', 'Todo'].map(period => [
            period,
            windowNav(scores.history?.dates ?? [], scores.history?.nav ?? [], period)
                .filter(point => Number.isFinite(point.value) && Number.isFinite(Date.parse(point.date)))
                .map(point => ({ date: formatDate(point.date, { day: '2-digit', month: 'short' }), value: point.value })),
        ]),
    ), [scores.history]);
    const effectivePeriod = periodData[chartPeriod].length >= 2 ? chartPeriod : 'Todo';
    const chartData = periodData[effectivePeriod];
    const hasDrawableHistory = periodData.Todo.length >= 2;
    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-[1600px] flex-col overflow-x-clip">
                {/* Header */}
                <div className="flex flex-col gap-4 mb-6 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex w-full flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                        <div className="flex min-w-0 items-center gap-3 sm:flex-1">
                            <div className="h-10 w-10 shrink-0 rounded-xl bg-gradient-to-br from-teal-500 to-blue-600 flex items-center justify-center">
                                <Wallet aria-hidden="true" className="h-5 w-5 text-white" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <h1 className="text-xl font-bold text-gray-100 sm:text-2xl">Resumen</h1>

                            </div>
                        </div>
                        {/* Acción principal de la página: antes solo existía dentro de la
                            pestaña «Posiciones», y con la cartera vacía el «Resumen» era un
                            callejón sin salida (auditoría UX 2026-10-27). */}
                        <div className="flex shrink-0 items-center gap-2">
                            <AddTransactionButton userId={userId} />
                            <RefreshPortfolioButton userId={userId} />
                        </div>
                    </div>
                </div>

                {partialMessage ? (
                    <div className="mb-4 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
                        Cartera parcialmente disponible: {partialMessage}. Reintenta en unos segundos.
                    </div>
                ) : null}

                {/* Tabs Navigation */}
                <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
                {/* Con teclado no hay barra de scroll: la region enfocable deja las
                    pestañas alcanzables con las flechas (WCAG 2.1.1). */}
                <div ref={tabViewportRef} role="region" aria-label="Secciones de la cartera" tabIndex={0} className="-mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
                    <TabsList className="bg-[#0a0a0a] border border-gray-800 p-1 rounded-xl mb-6 flex h-auto w-max max-w-none flex-nowrap gap-1 sm:h-9">
                    <TabsTrigger
                        value="resumen"
                        className="data-[state=active]:bg-gray-800 data-[state=active]:text-white rounded-lg px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2 min-h-[44px] sm:min-h-0 sm:py-2 whitespace-nowrap"
                    >
                        <LayoutDashboard aria-hidden="true" className="h-4 w-4" />
                        Resumen
                    </TabsTrigger>
                    <TabsTrigger
                        value="posiciones"
                        className="data-[state=active]:bg-gray-800 data-[state=active]:text-white rounded-lg px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2 min-h-[44px] sm:min-h-0 sm:py-2 whitespace-nowrap"
                    >
                        <Briefcase aria-hidden="true" className="h-4 w-4" />
                        Posiciones
                    </TabsTrigger>
                    <TabsTrigger
                        value="movimientos"
                        className="data-[state=active]:bg-gray-800 data-[state=active]:text-white rounded-lg px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2 min-h-[44px] sm:min-h-0 sm:py-2 whitespace-nowrap"
                    >
                        <History aria-hidden="true" className="h-4 w-4" />
                        Movimientos
                    </TabsTrigger>
                    <TabsTrigger
                        value="dividendos"
                        className="data-[state=active]:bg-gray-800 data-[state=active]:text-white rounded-lg px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2 min-h-[44px] sm:min-h-0 sm:py-2 whitespace-nowrap"
                    >
                        <Coins aria-hidden="true" className="h-4 w-4" />
                        Dividendos
                    </TabsTrigger>
                    <TabsTrigger
                        value="prevision"
                        className="data-[state=active]:bg-gray-800 data-[state=active]:text-white rounded-lg px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2 min-h-[44px] sm:min-h-0 sm:py-2 whitespace-nowrap"
                    >
                        <TrendingUp aria-hidden="true" className="h-4 w-4" />
                        Previsión
                    </TabsTrigger>
                    <TabsTrigger
                        value="estrategia"
                        className="data-[state=active]:bg-gray-800 data-[state=active]:text-white rounded-lg px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2 min-h-[44px] sm:min-h-0 sm:py-2 whitespace-nowrap"
                    >
                        <Brain aria-hidden="true" className="h-4 w-4" />
                        Factores
                    </TabsTrigger>
                </TabsList>
                </div>

                {/* Tab: Resumen */}
                <TabsContent value="resumen" className="mt-0">
                    {/* Métricas en fila */}
                    <div className="mb-6">
                        <PortfolioSummary summary={summary} />
                        <PortfolioDataNotice quality={summary.quality} />
                    </div>

                    {/* Grid: gráfico de rendimiento + distribución */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        {/* Panel Izquierdo: Gráfico de Rendimiento */}
                        <div className="bg-[#111111] border border-gray-800 rounded-2xl p-4 sm:p-6">
                            <div className="flex flex-col gap-3 mb-4 sm:flex-row sm:items-center sm:justify-between">
                                <h2 className="text-gray-400 text-sm font-medium">Valor de la cartera</h2>
                                {hasDrawableHistory ? <div className="flex w-full flex-wrap gap-1 sm:w-auto" role="group" aria-label="Periodo del gráfico de valor">
                                    {['1S', '1M', '3M', '6M', 'YTD', '1A', 'Todo'].map((period) => (
                                        <button
                                            key={period}
                                            onClick={() => setChartPeriod(period)}
                                            disabled={periodData[period].length < 2}
                                            aria-pressed={effectivePeriod === period}
                                            className={`min-h-[44px] min-w-11 flex-1 px-1 py-2 text-xs rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed sm:flex-none sm:px-2 sm:py-1 ${effectivePeriod === period
                                                    ? 'bg-gray-700 text-white'
                                                    : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800'
                                                }`}
                                        >
                                            {period}
                                        </button>
                                    ))}
                                </div> : null}
                            </div>

                            <div className="mb-4">
                                <p className="text-3xl font-bold text-white">
                                    {formatMoney(summary.totalValue, summary.baseCurrency)}
                                </p>
                                {summary.holdings.length === 0 ? (
                                    <div className="mt-2 space-y-3">
                                        <p className="text-sm text-gray-400">
                                            Aún no tienes posiciones. Registra tu primera compra y verás aquí el valor, la rentabilidad y el reparto de tu cartera.
                                        </p>
                                        <AddTransactionButton userId={userId} />
                                    </div>
                                ) : !hasCostBasis(summary) ? (
                                    <p className="text-sm text-gray-500">
                                        Rentabilidad no disponible: falta una base de coste válida. La cifra superior es el valor neto, no el beneficio del periodo.
                                    </p>
                                ) : (
                                <p className={`text-sm flex flex-wrap items-center gap-1 ${summary.totalGain >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {summary.totalGain >= 0 ? <TrendingUp aria-hidden="true" className="h-4 w-4" /> : <TrendingDown aria-hidden="true" className="h-4 w-4" />}
                                    <span className="whitespace-nowrap">G/P desde compra:</span>
                                    {formatPercent(summary.totalGainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' })}
                                    <span className="text-gray-500">
                                        ({formatMoney(summary.totalGain, summary.baseCurrency, { signDisplay: 'auto' })})
                                    </span>
                                </p>
                                )}
                            </div>

                            {/* Gráfico de área */}
                            <div className="h-[200px]">
                                {chartData.length < 2 ? (
                                    <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-gray-800 text-sm text-gray-500">
                                        Aún no hay una serie continua de valoraciones verificables: las fotos incompletas no se dibujan.
                                    </div>
                                ) : (
                                <PortfolioNavChart data={chartData} positive={summary.totalGain >= 0} currency={summary.baseCurrency} />
                                )}
                            </div>
                            {chartData.length >= 2 && scores.history?.rebuild_reset_date ? (
                                <p className="mt-2 text-xs text-amber-300/90" data-testid="twr-rebuild-reset">
                                    {`Reconstrucción: serie reiniciada el ${formatDate(scores.history.rebuild_reset_date, { day: '2-digit', month: 'short', year: 'numeric' })}. El rendimiento acumulado (TWR) vuelve a empezar desde 0 en esa fecha; lo anterior era una serie reconstruida solo con posiciones.`}
                                </p>
                            ) : null}
                        </div>

                        {/* Panel Derecho: Pie Chart Completo */}
                        <PortfolioAllocation
                            holdings={summary.holdings}
                            cash={summary.cash}
                            baseCurrency={summary.baseCurrency}
                        />
                    </div>

                    {/* Tearsheet: Sharpe, drawdown, win rate */}
                    <div className="mt-6">
                        <PortfolioTearsheet tearsheet={tearsheet} />
                    </div>
                    {/* Salida cruzada a las otras dos páginas de riesgo: el
                        resumen es pesos y precio; el riesgo medido está en
                        Inteligencia y las concentraciones en Exposiciones.
                        Sin frase de arquitectura: un subtítulo de una línea y
                        los dos enlaces (quick win UX 2). */}
                    <div className="mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-gray-700/50 bg-surface-1 p-3">
                        <p className="min-w-0 flex-1 basis-60 text-sm font-medium text-gray-300">
                            Riesgo y exposiciones, en detalle:
                        </p>
                        <Link className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-gray-700 px-3 py-2 text-sm text-gray-300 transition hover:border-teal-700 hover:text-teal-300 sm:min-h-0 sm:py-1.5" href="/portfolio/intelligence">
                            <Activity aria-hidden="true" className="h-4 w-4" /> Riesgo y rendimiento
                        </Link>
                        <Link className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-gray-700 px-3 py-2 text-sm text-gray-300 transition hover:border-teal-700 hover:text-teal-300 sm:min-h-0 sm:py-1.5" href="/risk">
                            <Gauge aria-hidden="true" className="h-4 w-4" /> Exposiciones
                        </Link>
                    </div>

                </TabsContent>

                {/* Tab: Posiciones */}
                {/* Tab: Prevision */}
                <TabsContent value="prevision" className="mt-0">
                    <SavingsProjection />
                    <h2 className="mb-3 text-lg font-semibold text-gray-100">Valoración de la cartera actual</h2>
                    {forecast ? (
                        <PortfolioForecast forecast={forecast} />
                    ) : (
                        <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
                            No se pudo cargar la previsión. Reintenta en unos segundos.
                        </p>
                    )}
                </TabsContent>

                <TabsContent value="dividendos" className="mt-0">
                    {dividends ? (
                        <PortfolioDividends projection={dividends} userId={userId} />
                    ) : (
                        <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
                            No se pudo cargar la proyección de dividendos. Reintenta en unos segundos.
                        </p>
                    )}
                </TabsContent>

                <TabsContent value="posiciones" className="mt-0">
                    <PortfolioHoldings holdings={summary.holdings} userId={userId} cash={summary.cash} baseCurrency={summary.baseCurrency} />
                </TabsContent>

                {/* Tab: Movimientos */}
                <TabsContent value="movimientos" className="mt-0">
                    <div className="max-w-4xl">
                        <PortfolioTransactions transactions={transactions} userId={userId} page={transactionPage} />
                    </div>
                </TabsContent>

                {/* Tab: factores calculados */}
                <TabsContent value="estrategia" className="mt-0">
                    <PortfolioScores scores={scores} />
                </TabsContent>

            </Tabs>

        </main>
    );
}

