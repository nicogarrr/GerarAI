'use client';

import { useEffect, useRef, useState } from 'react';
import { BarChart3, Loader2, Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import RadarGlobalView from './RadarGlobalView';
import EnhancedProPicksContent from './EnhancedProPicksContent';
import GemsView from './GemsView';
import DeepValueView from './DeepValueView';
import PaperTradingView from './PaperTradingView';
import MonthlyRebalanceView from './MonthlyRebalanceView';
import StrategyFactsheet from './StrategyFactsheet';
import TrackRecordView from './TrackRecordView';
import StrategySelector from './StrategySelector';
import WalkForwardResults from './WalkForwardResults';
import DcaBacktestPanel from './DcaBacktestPanel';
import { STRATEGY_CATALOG, mergeStrategies } from './monthlyRebalance';
import { runWalkForwardBacktest, type WalkForwardBacktestResult } from '@/lib/actions/propicks-backtest.actions';
import { generateProPicksForStrategy, type ProPick } from '@/lib/actions/proPicks.actions';

interface ProPicksTabsProps {
    initialTab?: 'picks' | 'paper';
    strategies: Array<{ id: string; name: string; description: string }>;
    initialPicks: ProPick[];
    generatedAt?: string;
    passedCount?: number | null;
}

export default function ProPicksTabs({ strategies, initialPicks, generatedAt, passedCount = null, initialTab = 'picks' }: ProPicksTabsProps) {
    const merged = mergeStrategies(strategies);
    const [activeTab, setActiveTab] = useState<string>(initialTab);
    const [currentStrategy, setCurrentStrategy] = useState<string>(merged[0]?.id ?? 'adaptive');
    const [walkForward, setWalkForward] = useState<WalkForwardBacktestResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // El motor walk-forward NO se dispara al montar: se lanza la primera vez
    // que se abre la pestaña de Backtesting (o con «Ejecutar backtest»).
    // Antes costaba una corrida completa a quien solo quería ver los Picks.
    const backtestStarted = useRef(false);
    // F383: los picks iniciales (ranking global del embudo) NO se asocian a
    // ninguna estrategia; cada estrategia, también la inicial, carga los suyos
    // por la ruta strategy-aware. Nunca se exportan picks de otra estrategia.
    const [picksByStrategy, setPicksByStrategy] = useState<Record<string, { picks: ProPick[]; asOf: string | null }>>({});
    const [strategyPicksError, setStrategyPicksError] = useState<string | null>(null);
    // Corte del run que alimenta la selección vigente; sube desde Selección IA
    // cuando una generación/actualización trae un run distinto.
    const [latestRunAsOf, setLatestRunAsOf] = useState<string | null>(generatedAt ?? null);

    // Un run nuevo invalida los picks cacheados de TODAS las estrategias: se
    // calculan del último run del embudo, así que el corte viejo ya no es el
    // vigente. Sin esto, tras «Generar selección ahora» el rebalanceo seguía
    // mostrando los picks del run anterior (o «0 valores» si no había run).
    const handleRunUpdated = (asOf: string | null) => {
        setLatestRunAsOf(asOf);
        setPicksByStrategy({});
        setStrategyPicksError(null);
    };

    const availableIds = new Set(strategies.map((s) => s.id));
    const currentMerged = merged.find((s) => s.id === currentStrategy) ?? merged[0];
    const currentAvailable = currentMerged ? availableIds.has(currentMerged.id) : false;

    const runBacktest = async () => {
        // Motor walk-forward point-in-time: agnóstico de estrategia (momentum
        // 12-1M sobre universo líquido, costes de 15pb por pata, benchmark SPY).
        // El backtest por estrategia se publicará cuando haya fundamentales
        // point-in-time; hasta entonces NO se simula nada con datos de hoy.
        setLoading(true);
        setError(null);
        try {
            const output = await runWalkForwardBacktest();
            if ('error' in output) {
                setError(output.error);
                setWalkForward(null);
            } else {
                setWalkForward(output);
            }
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : String(caught));
            setWalkForward(null);
        } finally {
            setLoading(false);
        }
    };

    const handleTabChange = (tab: string) => {
        setActiveTab(tab);
        // El backtest arranca al entrar en su pestaña, una sola vez: es la
        // respuesta a un evento, no un efecto.
        if (tab === 'backtest' && !backtestStarted.current) {
            backtestStarted.current = true;
            void runBacktest();
        }
    };

    const handleStrategyChange = (strategyId: string) => {
        setCurrentStrategy(strategyId);
        setStrategyPicksError(null);
    };

    const cachedStrategyPicks = picksByStrategy[currentStrategy];
    const strategyPicks = cachedStrategyPicks?.picks;
    useEffect(() => {
        // No enriquecer otra pestaña hasta que el usuario la abra.
        if (activeTab !== 'estrategia') return;
        // Cache válida solo si viene del mismo run que la selección vigente.
        if (cachedStrategyPicks !== undefined && cachedStrategyPicks.asOf === latestRunAsOf) return;
        let cancelled = false;
        generateProPicksForStrategy(currentStrategy)
            .then((picks) => {
                if (!cancelled) {
                    setPicksByStrategy((prev) => ({
                        ...prev,
                        [currentStrategy]: { picks, asOf: picks[0]?.asOf ?? latestRunAsOf },
                    }));
                }
            })
            .catch(() => {
                if (!cancelled) setStrategyPicksError('No se pudieron cargar los picks de esta estrategia.');
            });
        return () => {
            cancelled = true;
        };
    }, [activeTab, currentStrategy, cachedStrategyPicks, latestRunAsOf]);

    return (
        <Tabs value={activeTab} onValueChange={handleTabChange} className="mt-6 w-full min-w-0">
            {/* En movil las pestañas envuelven a dos filas: antes se cortaban a
                media palabra («Estrategia y rebalanc…») y el resto solo se
                alcanzaba por scroll horizontal sin affordance. Todos los
                triggers son alcanzables con flechas (tablist de Radix). */}
            <TabsList
                aria-label="Secciones de Pro Picks"
                className="flex h-auto w-full min-w-0 max-w-full flex-wrap justify-start gap-1 border border-gray-700 bg-gray-800 p-1 pb-2 text-gray-400 sm:inline-flex sm:h-auto sm:w-auto sm:max-w-none sm:pb-[3px]"
            >
                <TabsTrigger value="picks" className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap px-2.5 text-sm data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300 sm:px-3">
                    Selección IA
                </TabsTrigger>
                <TabsTrigger value="joyas" className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap px-2.5 text-sm data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300 sm:px-3">
                    Joyas
                </TabsTrigger>
                <TabsTrigger value="deepvalue" className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap px-2.5 text-sm data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300 sm:px-3">
                    Deep value
                </TabsTrigger>
                <TabsTrigger value="estrategia" className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap px-2.5 text-sm data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300 sm:px-3">
                    Estrategia y rebalanceo
                </TabsTrigger>
                <TabsTrigger value="backtest" className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap px-2.5 text-sm data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300 sm:px-3">
                    Backtesting
                </TabsTrigger>
                <TabsTrigger value="paper" className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap px-2.5 text-sm data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300 sm:px-3">Resultados simulados de la IA</TabsTrigger>
                <TabsTrigger value="radar" className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap px-2.5 text-sm data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300 sm:px-3">Radar global</TabsTrigger>
            </TabsList>

            <TabsContent value="paper" className="mt-6"><PaperTradingView /></TabsContent>
            <TabsContent value="radar" className="mt-6">
                {activeTab === 'radar' && <RadarGlobalView />}
            </TabsContent>

            {/* forceMount: Radix desmonta el panel inactivo y EnhancedProPicksContent
                se sembraba con initialPicks del SSR; al generar/actualizar la
                selección y volver a la pestaña el estado se perdía (reproducido
                en prod 2026-10-19). Montado siempre, la selección y los filtros
                sobreviven al cambio de pestaña.
                Pero @radix-ui/react-tabs 1.2.1 calcula `hidden: !present`: con
                forceMount present es siempre true y el panel quedaba VISIBLE en
                las 5 pestañas (la parrilla de picks encima/debajo del contenido
                propio, Tester 6). contentProps se expande después, así que este
                `hidden` explícito manda: montado siempre, visible solo en su
                pestaña. */}
            <TabsContent value="picks" forceMount hidden={activeTab !== 'picks'} className="mt-6">
                <EnhancedProPicksContent initialPicks={initialPicks} generatedAt={generatedAt} initialPassedCount={passedCount} onRunUpdated={handleRunUpdated} />
            </TabsContent>

            <TabsContent value="joyas" className="mt-6">
                {activeTab === 'joyas' && <GemsView />}
            </TabsContent>

            <TabsContent value="deepvalue" className="mt-6">
                {activeTab === 'deepvalue' && <DeepValueView />}
            </TabsContent>

            {/* Selector + ficha + rebalanceo son la MISMA estrategia con dos
                lecturas: el `currentStrategy` que elige el selector es el que
                gobierna el rebalanceo mensual de abajo. Partirlos en dos
                pestañas obligaba a saltar para ver si el rebalanceo que se
                leía era el de la estrategia elegida. */}
            <TabsContent value="estrategia" className="mt-6 space-y-4">
                <Card className="flex min-w-0 flex-col gap-4 rounded-lg border border-gray-700 bg-gray-800/50 p-4 md:flex-row md:items-center md:justify-between">
                    <StrategySelector
                        strategies={strategies}
                        catalog={STRATEGY_CATALOG}
                        currentStrategy={currentStrategy}
                        onStrategyChange={handleStrategyChange}
                    />
                </Card>

                {currentMerged && (
                    <StrategyFactsheet
                        strategyId={currentMerged.id}
                        name={currentMerged.name}
                        description={currentMerged.description}
                        available={currentAvailable}
                    />
                )}

                <MonthlyRebalanceView
                    key={currentStrategy}
                    currentPicks={strategyPicks ?? []}
                    picksStatus={strategyPicks !== undefined ? 'ready' : strategyPicksError ? 'error' : 'loading'}
                    picksError={strategyPicksError}
                    strategyId={currentStrategy}
                    strategyName={currentMerged?.name}
                />
            </TabsContent>

            <TabsContent value="backtest" className="mt-6 space-y-4">
                {/* Track record vivo de las selecciones reales (snapshots
                    mensuales point-in-time), encima del baseline walk-forward:
                    es la evidencia que de verdad le importa a Nico. */}
                <TrackRecordView />

                <Card className="flex min-w-0 flex-col gap-4 rounded-lg border border-gray-700 bg-gray-800/50 p-4 md:flex-row md:items-center md:justify-between">
                    <p className="max-w-xl text-sm leading-6 text-gray-400">
                        Baseline walk-forward point-in-time (momentum 12-1M,
                        universo líquido de 30 valores, costes 15 pb por pata,
                        SPY como benchmark). No valida la selección IA:
                        valida que el motor no mira el futuro. El backtest por
                        estrategia con fundamentales point-in-time llegará
                        cuando haya TTM persistido.
                    </p>
                    <Button
                        onClick={() => runBacktest()}
                        disabled={loading}
                        aria-busy={loading}
                        className="h-11 w-full gap-2 md:w-auto"
                    >
                        {loading ? (
                            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                        ) : (
                            <Play aria-hidden="true" className="h-4 w-4" />
                        )}
                        {loading ? 'Calculando...' : 'Ejecutar backtest'}
                    </Button>
                </Card>

                {error && (
                    <Card className="rounded-lg border border-red-700 bg-red-900/20 p-6 text-center">
                        <p className="text-red-400">{error}</p>
                        <p className="text-sm text-gray-400 mt-2">
                            No se pudo calcular el backtest. Comprueba tu conexión e inténtalo de nuevo.
                        </p>
                        <Button
                            onClick={() => runBacktest()}
                            disabled={loading}
                            aria-busy={loading}
                            className="mt-4 h-11 w-full gap-2 sm:w-auto"
                        >
                            {loading ? (
                                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                            ) : (
                                <Play aria-hidden="true" className="h-4 w-4" />
                            )}
                            Reintentar
                        </Button>
                    </Card>
                )}

                {loading && !walkForward && (
                    <Card aria-busy="true" className="flex items-center justify-center gap-3 rounded-lg border border-gray-700 bg-gray-800/50 p-10 text-gray-400">
                        <Loader2 aria-hidden="true" className="h-5 w-5 animate-spin text-teal-400" />
                        <span>Calculando backtest walk-forward con datos históricos... puede tardar unos segundos.</span>
                    </Card>
                )}

                {walkForward && !loading && <WalkForwardResults result={walkForward} />}

                {!loading && !error && !walkForward && (
                    <Card className="flex flex-col items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/50 p-10 text-gray-500">
                        <BarChart3 aria-hidden="true" className="h-10 w-10 text-gray-500" />
                        <p className="text-sm">Pulsa «Ejecutar backtest» para lanzar la simulación walk-forward point-in-time.</p>
                    </Card>
                )}

                <DcaBacktestPanel />
            </TabsContent>
        </Tabs>
    );
}
