'use client';

import { useMemo, useRef, useState } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import Link from 'next/link';
import { TrendingUp, Sparkles, ArrowRight, Loader2, RefreshCw, Clock, Plus, Check } from 'lucide-react';
import EnhancedProPicksFilters, { ProPicksFilters } from './EnhancedProPicksFilters';
import { generateEnhancedProPicksWithRun, type ProPick } from '@/lib/actions/proPicks.actions';
import { generateFunnelRunNow } from '@/lib/actions/propicks-funnel.actions';
import { allNeutralCategory, categoryDisplay } from '@/lib/propicks/category-display';
import { CATEGORY_KEYS, categoryNeutralNote } from './category-display';
import { addToWatchlist } from '@/lib/actions/watchlist.actions';
import { formatCompanyName, formatNumber, formatPercent, formatPrice, formatUserDate, formatUserDateTime, formatCountEs } from '@/lib/format';
import { etiquetaSector } from '@/lib/labels';
import { t } from '@/lib/i18n/t';
import { toast } from 'sonner';

interface EnhancedProPicksContentProps {
    initialPicks: ProPick[];
    generatedAt?: string;
    initialPassedCount?: number | null;
    /** Avisa al contenedor cuando la selección visible pasa a venir de otro run
     *  (generación o actualización): invalida los picks cacheados por estrategia
     *  para que «Estrategia y rebalanceo» no muestre el run viejo (o 0 valores). */
    onRunUpdated?: (asOf: string | null) => void;
}

export default function EnhancedProPicksContent({ initialPicks, generatedAt, initialPassedCount = null, onRunUpdated }: EnhancedProPicksContentProps) {
    const [picks, setPicks] = useState<ProPick[]>(initialPicks);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [refreshStatus, setRefreshStatus] = useState<string | null>(null);
    const [lastGenerated, setLastGenerated] = useState<string | null>(generatedAt || null);
    const [passedCount, setPassedCount] = useState<number | null>(initialPassedCount);
    const [filters, setFilters] = useState<ProPicksFilters>({
        timePeriod: 'month',
        limit: 20,
        minScore: 70,
        sector: 'all',
        sortBy: 'score',
    });
    // Los controles son un borrador; solo una respuesta válida cambia el corte visible.
    const [appliedFilters, setAppliedFilters] = useState<ProPicksFilters>(filters);
    const requestInFlight = useRef(false);
    const [followed, setFollowed] = useState<Record<string, boolean>>({});
    const [following, setFollowing] = useState<string | null>(null);

    const handleFollow = async (e: React.MouseEvent, symbol: string, company: string) => {
        e.preventDefault();
        e.stopPropagation();
        if (followed[symbol] || following) return;
        setFollowing(symbol);
        try {
            const res = await addToWatchlist(symbol, company);
            if (res.success) {
                setFollowed((prev) => ({ ...prev, [symbol]: true }));
                toast.success(`${symbol} añadido a la watchlist`);
            } else {
                toast.error('No se pudo añadir a la watchlist');
            }
        } catch {
            toast.error('No se pudo añadir a la watchlist');
        } finally {
            setFollowing(null);
        }
    };

    const loadPicks = async () => {
        // El ref cierra también dos clics antes del siguiente render de React.
        if (requestInFlight.current) return;
        requestInFlight.current = true;
        const requestedFilters = { ...filters };
        setLoading(true);
        setError(null);
        setRefreshStatus(null);
        try {
            const result = await generateEnhancedProPicksWithRun(requestedFilters);
            setPicks(result.picks);
            if (result.runAsOf !== lastGenerated) onRunUpdated?.(result.runAsOf);
            setLastGenerated(result.runAsOf);
            setPassedCount(result.passedCount);
            setAppliedFilters(requestedFilters);
            setRefreshStatus(result.picks.length
                ? `Selección consultada: ${formatCountEs(result.picks.length, 'empresa', 'empresas')}.`
                // Mensaje honesto del 0: distingue "tus filtros excluyen todo"
                // de "el embudo no seleccionó nada", que no es fallo del usuario.
                : result.passedCount
                    ? `Consulta completada: 0 empresas con estos filtros. El último embudo sí seleccionó ${result.passedCount}; baja la puntuación mínima o amplía el sector para verlas.`
                    : 'Consulta completada: 0 empresas. El último embudo no seleccionó ninguna con los datos disponibles; no es un fallo de tus filtros.');
        } catch {
            setError('No se pudo actualizar la selección. Los resultados anteriores se conservan.');
        } finally {
            requestInFlight.current = false;
            setLoading(false);
        }
    };

    const handleApplyFilters = loadPicks;
    const handleRefresh = loadPicks;

    // Sin ningún run publicado, «Actualizar» relee una lista vacía: la acción
    // real es ejecutar el embudo (POST /api/propicks/runs) y consultar después.
    const handleGenerateRun = async () => {
        if (requestInFlight.current) return;
        requestInFlight.current = true;
        setLoading(true);
        setError(null);
        setRefreshStatus(null);
        try {
            const run = await generateFunnelRunNow();
            if ('error' in run) {
                setError('No se pudo generar la selección. Inténtalo de nuevo.');
                return;
            }
            setRefreshStatus(run.passed_count > 0
                ? run.passed_count === 1
                    ? 'Selección generada: 1 empresa supera el embudo.'
                    : `Selección generada: ${formatCountEs(run.passed_count, 'empresa', 'empresas')} superan el embudo.`
                : `Selección generada: 0 de ${run.universe_size} empresas del universo superan el embudo con los datos disponibles; ninguna cumple todos los criterios ahora mismo.`);
            requestInFlight.current = false;
            setLoading(false);
            await loadPicks();
            return;
        } catch {
            setError('No se pudo generar la selección. Inténtalo de nuevo.');
        } finally {
            requestInFlight.current = false;
            setLoading(false);
        }
    };

    const formatLastGenerated = (isoString: string | null) => {
        if (!isoString) return null;
        // formatUserDateTime fija la zona (Europe/Madrid): el SSR corre en UTC y
        // el navegador en hora local, sin timeZone el texto difiere y React
        // rompe la hidratación (F23, #418).
        return formatUserDateTime(isoString);
    };

    // Estado MEDIDO de las categorías en la ejecución visible: se deriva de estos
    // picks (categoryDisplay honra el flag de ausencia de cada categoría).
    const neutralNote = useMemo(
        () => categoryNeutralNote(CATEGORY_KEYS.filter((key) => allNeutralCategory(picks, key)), picks.length),
        [picks],
    );

    const getScoreColor = (score: number) => {
        if (score >= 80) return 'text-green-400 bg-green-500/10 border-green-500/20';
        if (score >= 70) return 'text-teal-400 bg-teal-500/10 border-teal-500/20';
        return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20';
    };

    const getGradeColor = (grade: string) => {
        if (grade.startsWith('A')) return 'bg-green-500';
        if (grade.startsWith('B')) return 'bg-teal-500';
        return 'bg-yellow-500';
    };

    return (
        <div className="grid w-full min-w-0 grid-cols-1 gap-4 sm:gap-6 xl:grid-cols-[18rem_minmax(0,1fr)]">
            {/* Sidebar con filtros */}
            <div className="min-w-0">
                <EnhancedProPicksFilters
                    filters={filters}
                    disabled={loading}
                    // F184: ordenar por una categoría neutral en TODOS los
                    // picks del run es ordenar por una constante (50): la
                    // opción se deshabilita y se etiqueta n/d.
                    neutralSorts={(['momentum', 'value'] as const).filter((key) => allNeutralCategory(picks, key))}
                    onFiltersChange={setFilters}
                    onApply={handleApplyFilters}
                />

                {/* Refresh Button */}
                <Card className="mt-4 p-4 border-gray-700 bg-gray-800/50">
                    <Button
                        onClick={handleRefresh}
                        disabled={loading}
                        aria-busy={loading}
                        className="min-h-11 w-full gap-2 whitespace-normal text-center leading-tight"
                    >
                        {loading ? (
                            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                        ) : (
                            <RefreshCw aria-hidden="true" className="h-4 w-4" />
                        )}
                        {/* QA: el botón debe anunciar el estado por sí mismo
                            (primario legible y etiqueta que cambia). */}
                        <span>{loading ? 'Actualizando selección...' : 'Actualizar selección'}</span>
                    </Button>
                    <p aria-live="polite" role="status" className="mt-3 text-xs text-gray-400">
                        {loading ? 'Consultando selección...' : refreshStatus}
                    </p>
                    {lastGenerated && (
                        <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
                            <Clock aria-hidden="true" className="h-3 w-3" />
                            Datos: {formatLastGenerated(lastGenerated)}
                        </div>
                    )}
                </Card>

                {/* Una sola línea medida: qué categorías entran sin dato (50 = «sin dato», no un score). */}
                {neutralNote ? (
                    <p className="mt-4 text-xs leading-relaxed text-gray-500">{neutralNote.marker} {neutralNote.text}</p>
                ) : null}
            </div>

            {/* Resultados */}
            <div className="min-w-0">
                {/* Header */}
                <div className="mb-6">
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <Badge variant="outline" className="text-teal-400 border-teal-400">
                                {picks.length > 0 ? `Top ${formatNumber(picks.length, { maximumFractionDigits: 0 })}` : 'Sin selección'}
                            </Badge>
                        </div>
                        {loading && (
                            <div aria-busy="true" className="flex items-center gap-2 text-sm text-gray-400">
                                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                                Procesando...
                            </div>
                        )}
                    </div>
                    {picks.length > 0 ? (
                        <p className="text-sm text-gray-400">
                            Acciones seleccionadas con puntuación mínima de {appliedFilters.minScore} ordenadas por {
                                appliedFilters.sortBy === 'score' ? 'puntuación general' :
                                    appliedFilters.sortBy === 'momentum' ? 'momentum' :
                                        appliedFilters.sortBy === 'value' ? 'valor' :
                                            appliedFilters.sortBy === 'growth' ? 'crecimiento' :
                                                'rentabilidad'
                            }
                        </p>
                    ) : null}
                </div>

                {error && (
                    <Card className="p-6 rounded-lg border border-red-700 bg-red-900/20 mb-4 text-center">
                        <p className="text-red-400">{error}</p>
                        <p className="text-sm text-gray-400 mt-2">
                            Reintenta para consultar el último run disponible.
                        </p>
                        <Button
                            onClick={handleRefresh}
                            disabled={loading}
                            aria-busy={loading}
                            className="mt-4 h-11 w-full gap-2 sm:w-auto"
                        >
                            {loading ? (
                                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                            ) : (
                                <RefreshCw aria-hidden="true" className="h-4 w-4" />
                            )}
                            {t('common.actions.retry')}
                        </Button>
                    </Card>
                )}

                {picks.length === 0 && !error ? (
                    <Card className="p-8 rounded-lg border border-gray-700 bg-gray-800/50 text-center">
                        <Sparkles aria-hidden="true" className="h-12 w-12 mx-auto mb-4 text-gray-500" />
                        <p className="text-gray-300 font-medium">
                            {!lastGenerated ? 'Sin selección publicada' : passedCount === 0 ? 'Sin candidatos aptos' : t('propicks.noResults')}
                        </p>
                        <p className="text-sm text-gray-500 mt-2">
                            {!lastGenerated &&
                                'El embudo todavía no ha publicado un run completado. Pulsa «Generar selección ahora» para ejecutarlo con las empresas disponibles.'}
                            {lastGenerated && passedCount === 0 &&
                                `La selección del ${formatLastGenerated(lastGenerated)} no contiene candidatos que superen los criterios del embudo. Si el espacio de trabajo es nuevo o los datos se recargaron después, ejecuta la selección de nuevo para evaluar las empresas con los datos de mercado actuales.`}
                            {lastGenerated && passedCount !== 0 &&
                                `Ninguna acción de la selección del ${formatLastGenerated(lastGenerated)} cumple los filtros actuales (puntuación ≥ ${appliedFilters.minScore}${appliedFilters.sector !== 'all' ? `, sector ${etiquetaSector(appliedFilters.sector)}` : ''}). Prueba a bajar la puntuación mínima o cambiar de sector.`}
                        </p>
                        <Button
                            onClick={lastGenerated && passedCount !== 0 ? handleRefresh : handleGenerateRun}
                            disabled={loading}
                            aria-busy={loading}
                            className="mt-4 h-11 w-full gap-2 sm:w-auto"
                        >
                            {loading ? (
                                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                            ) : (
                                <RefreshCw aria-hidden="true" className="h-4 w-4" />
                            )}
<span>{lastGenerated ? (loading ? 'Actualizando selección...' : 'Actualizar selección') : (loading ? 'Generando selección...' : 'Generar selección ahora')}</span>
                        </Button>
                    </Card>
                ) : picks.length > 0 ? (
                    <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
                        {picks.map((pick, index) => (
                            <Link
                                key={pick.symbol}
                                href={`/research/${pick.symbol}`}
                                className="block"
                            >
                                <Card className="h-full min-w-0 rounded-lg border border-gray-700 bg-gray-800/50 p-4 transition-all duration-200 group hover:bg-gray-800 sm:p-5">
                                    <div className="mb-3 flex min-w-0 items-start justify-between gap-3">
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="text-xs font-bold text-gray-500 px-2 py-1 bg-gray-900 rounded">
                                                    #{index + 1}
                                                </span>
                                                <h3 className="text-lg font-bold text-gray-100 group-hover:text-teal-400 transition-colors">
                                                    {pick.symbol}
                                                </h3>
                                                {pick.isStrongBuy && (
                                                    <span className="px-2 py-0.5 rounded text-[10px] font-bold text-white bg-gradient-to-r from-teal-500 to-emerald-500 animate-pulse">
                                                        💎 JOYA
                                                    </span>
                                                )}
                                                {!pick.isStrongBuy && (
                                                    <span className={`px-2 py-0.5 rounded text-xs font-bold text-white ${getGradeColor(pick.grade)}`}>
                                                        {pick.grade}
                                                    </span>
                                                )}
                                            </div>
                                            <p className="line-clamp-1 min-w-0 break-words text-sm text-gray-400">{formatCompanyName(pick.company)}</p>
                                            {pick.sector && (
                                                <p className="mt-1 break-words text-xs text-gray-500">{etiquetaSector(pick.sector)}</p>
                                            )}
                                        </div>
                                        <div className={`text-right px-3 py-2 rounded-lg border ${getScoreColor(pick.score)}`}>
                                            <div className="text-2xl font-bold">
                                                {formatNumber(pick.score, { maximumFractionDigits: 1 })}
                                            </div>
                                            <div className="text-xs">Puntuación</div>
                                        </div>
                                    </div>

                                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                                        {pick.currentPrice > 0 && pick.priceAsOf && pick.priceCurrency && (
                                            <div>
                                                <div className="text-xl font-semibold text-gray-100">
                                                    {formatPrice(pick.currentPrice, pick.priceCurrency)}
                                                </div>
                                                <div className="text-xs text-gray-500">Precio registrado · {formatUserDate(pick.priceAsOf)}</div>
                                            </div>
                                        )}
                                        {pick.upsidePotential && pick.upsidePotential > 0 && (
                                            <div className="text-right">
                                                <div className={`text-xl font-bold ${pick.upsidePotential > 15 ? 'text-emerald-400' : 'text-green-400'}`}>
                                                    {formatPercent(pick.upsidePotential, { fromRatio: false, digits: 1, signDisplay: 'always' })}
                                                </div>
                                                <div className="text-xs text-gray-500">Potencial (12m)</div>
                                            </div>
                                        )}
                                    </div>

                                    {/* Category Scores (F184: una categoría neutral en v1 se
                                        muestra n/d, nunca como un «50» que parece score real) */}
                                    <div className="grid grid-cols-3 gap-2 mb-1">
                                        {([
                                            { label: 'Valor', key: 'value' as const },
                                            { label: 'Momentum', key: 'momentum' as const },
                                            { label: 'Rentab.', key: 'profitability' as const },
                                        ]).map(({ label, key }) => {
                                            const display = categoryDisplay(pick, key);
                                            return (
                                                <div className="text-center" key={key}>
                                                    <div className="text-xs text-gray-500">{label}</div>
                                                    {display.kind === 'neutral' ? (
                                                        <div className="text-sm font-semibold text-gray-500">n/d*</div>
                                                    ) : (
                                                        <div className={`text-sm font-semibold ${display.value >= 70 ? 'text-green-400' : 'text-gray-400'}`}>
                                                            {formatNumber(display.value, { maximumFractionDigits: 1 })}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                    {(['value', 'momentum', 'profitability'] as const).some((key) => categoryDisplay(pick, key).kind === 'neutral') && (
                                        <div className="text-[10px] leading-4 text-gray-500 mb-2">
                                            * Sin datos para puntuarla: entra neutral (50) en el score y no discrimina entre los picks actuales.
                                        </div>
                                    )}

                                    <div className="mb-3 rounded-md border border-teal-500/20 bg-teal-500/5 px-3 py-2">
                                        <span className="text-xs text-gray-400">
                                            Confianza:{' '}
                                            <span className="font-semibold text-teal-300">
                                                {pick.confidenceLevel} ({formatNumber(pick.confidence, { maximumFractionDigits: 0 })}/100)
                                            </span>
                                        </span>
                                    </div>

                                    {pick.confidenceReasons.length > 0 && (
                                        <div className="space-y-1.5 mb-3">
                                            {pick.confidenceReasons.slice(0, 3).map((reason, reasonIndex) => (
                                                <div key={reasonIndex} className="flex min-w-0 items-start gap-2 text-xs text-gray-300" title={`Dato verificado: ${reason.metric} = ${reason.value}`}>
                                                    <TrendingUp aria-hidden="true" className="h-3 w-3 text-teal-400 flex-shrink-0 mt-0.5" />
                                                    <span className="line-clamp-1 min-w-0 break-words">{reason.text}</span>
                                                </div>
                                            ))}
                                        </div>
                                    )}

                                    {pick.asOf && (
                                        <p className="text-[11px] text-gray-500 mb-3">
                                            {t('signals.asOf', { date: formatUserDate(pick.asOf) })}
                                        </p>
                                    )}

                                    <div className="flex items-center justify-between pt-3 border-t border-gray-700 mt-auto">
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={(e) => handleFollow(e, pick.symbol, pick.company)}
                                            disabled={!!followed[pick.symbol] || following === pick.symbol}
                                            aria-busy={following === pick.symbol}
                                            className="h-11 gap-1.5 text-xs text-gray-400 hover:text-teal-400 sm:h-8"
                                        >
                                            {following === pick.symbol ? (
                                                <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" />
                                            ) : followed[pick.symbol] ? (
                                                <Check aria-hidden="true" className="h-3 w-3 text-teal-400" />
                                            ) : (
                                                <Plus aria-hidden="true" className="h-3 w-3" />
                                            )}
                                            {followed[pick.symbol] ? t('propicks.followed') : t('propicks.follow')}
                                        </Button>
                                        {/* No es un <Button>: esta tarjeta entera
                                            es un <Link> y anidar un boton sin
                                            onClick dentro de un enlace produce
                                            dos elementos interactivos anidados
                                            (HTML invalido) y un boton que no
                                            hace nada. El enlace ya es la accion. */}
                                        <span className="inline-flex h-11 items-center gap-2 text-xs text-gray-400 group-hover:text-teal-400 sm:h-8">
                                            Ver análisis completo
                                            <ArrowRight aria-hidden="true" className="h-3 w-3" />
                                        </span>
                                    </div>
                                </Card>
                            </Link>
                        ))}
                    </div>
                ) : null}
            </div>
        </div>
    );
}
