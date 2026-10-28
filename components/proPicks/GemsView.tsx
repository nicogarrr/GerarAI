'use client';

import { useEffect, useState } from 'react';
import { Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { formatCompanyName, formatMarketCapUsd, formatPercent } from '@/lib/format';
import { getGems, reviewGems, type GemItem } from '@/lib/actions/propicks-gems.actions';
import { gemReasonLabel, gemReasonValue } from './gemsFormat';

export default function GemsView() {
    const [gems, setGems] = useState<GemItem[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [reviewing, setReviewing] = useState(false);
    // Resultado honesto de la última revisión: sin él, cuando la cadena LLM no
    // está disponible el botón parecía no hacer nada (cada joya volvía con un
    // discreto «Sin revisión IA» y ya).
    const [reviewStatus, setReviewStatus] = useState<string | null>(null);

    const load = async () => {
        setLoading(true);
        setError(null);
        const result = await getGems();
        if ('error' in result) setError(result.error);
        else setGems(result);
        setLoading(false);
    };

    const review = async () => {
        setReviewing(true);
        setError(null);
        setReviewStatus(null);
        const result = await reviewGems();
        if ('error' in result) {
            setError(result.error);
        } else {
            setGems(result);
            const reviewed = result.filter((gem) => gem.review_status === 'reviewed').length;
            setReviewStatus(reviewed > 0
                ? `Revisión IA completada: ${reviewed} de ${result.length} joyas revisadas.`
                : 'La revisión IA no está disponible ahora mismo. La lista es la selección determinista (calidad + valor + insiders + 13F), sin el filtro del modelo; inténtalo de nuevo más tarde.');
        }
        setReviewing(false);
    };

    useEffect(() => {
        // Carga inicial tras montar: el setState de load no es síncrono en el efecto.
        queueMicrotask(() => void load());
    }, []);

    const busy = loading || reviewing;

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-lg font-bold text-gray-100">Joyas ocultas</h3>
                <div className="flex gap-2">
                    <Button onClick={load} disabled={busy} variant="outline" className="h-11 gap-2">
                        {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="h-4 w-4" />}
                        Actualizar
                    </Button>
                    <Button onClick={review} disabled={busy || !gems?.length} aria-busy={reviewing} className="h-11 gap-2">
                        {reviewing ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <Sparkles aria-hidden="true" className="h-4 w-4" />}
                        {reviewing ? 'Revisando...' : 'Revisar con IA'}
                    </Button>
                </div>
            </div>

            {error && (
                <Card className="rounded-lg border border-red-700 bg-red-900/20 p-4 text-sm text-red-400">{error}</Card>
            )}

            <p aria-live="polite" role="status" className={reviewStatus ? 'text-sm text-amber-300' : 'sr-only'}>
                {reviewStatus}
            </p>

            {gems !== null && gems.length === 0 && !error && (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center">
                    <p className="font-medium text-gray-300">Sin joyas con los datos actuales</p>
                    <p className="mt-2 text-sm text-gray-500">
                        Ninguna empresa que supera el embudo reúne capitalización de 300 M$ a 10.000 M$, rentabilidad por FCF de al menos 5 % y precio de los últimos 7 días. No es un fallo: son criterios fijos y la lista cambia cuando llegan datos nuevos.
                    </p>
                    <Button onClick={load} disabled={busy} className="mt-4 h-11 gap-2">
                        <RefreshCw aria-hidden="true" className="h-4 w-4" />
                        Actualizar
                    </Button>
                </Card>
            )}

            <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
                {(gems ?? []).map((gem) => (
                    <Card key={gem.ticker} className="min-w-0 rounded-lg border border-gray-700 bg-gray-800/50 p-4 sm:p-5">
                        <div className="mb-3 flex items-start justify-between gap-3">
                            <div className="min-w-0">
                                <h4 className="text-lg font-bold text-gray-100">{gem.ticker}</h4>
                                <p className="truncate text-xs text-gray-500">
                                    {formatCompanyName(gem.name)}{gem.market_cap ? ` · ${formatMarketCapUsd(gem.market_cap)}` : ''}
                                </p>
                            </div>
                            {/* La puntuación con etiqueta y escala: un número
                                suelto («73,2») no decía qué era ni sobre cuánto
                                (Tester 6). */}
                            <span className="shrink-0 rounded bg-gray-900 px-2 py-1 text-right">
                                <span className="block text-[10px] font-medium uppercase tracking-wide text-gray-500">
                                    Puntuación
                                </span>
                                <span className="text-sm font-bold text-teal-300">
                                    {new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 }).format(gem.score)}
                                    <span className="text-[11px] font-medium text-teal-400/80">/100</span>
                                </span>
                            </span>
                        </div>

                        <ul className="space-y-1.5">
                            {gem.reasons.map((reason) => (
                                <li key={reason.key} className="text-sm">
                                    <div className="flex justify-between gap-3">
                                        <span className="text-gray-400">{gemReasonLabel(reason.key)}</span>
                                        <span className="font-medium text-gray-100">{gemReasonValue(reason)}</span>
                                    </div>
                                    <div className="text-[11px] text-gray-500">{reason.source}</div>
                                </li>
                            ))}
                        </ul>

                        {gem.review_status === 'reviewed' && (
                            <div className="mt-4 space-y-2 border-t border-gray-700 pt-3 text-sm">
                                <div className="flex items-center justify-between gap-2">
                                    <span className={gem.decision === 'veto' ? 'font-bold text-red-400' : 'font-bold text-green-400'}>
                                        {gem.decision === 'veto' ? 'Descartada por la IA' : 'Mantenida por la IA'}
                                    </span>
                                    {gem.confidence !== null && gem.confidence !== undefined && (
                                        <span className="text-xs text-gray-400">Confianza {formatPercent(gem.confidence, { digits: 0 })}</span>
                                    )}
                                </div>
                                {gem.thesis && <p className="text-gray-300">{gem.thesis}</p>}
                                {gem.decision === 'veto' && gem.veto_reason && <p className="text-red-300">{gem.veto_reason}</p>}
                                {!!gem.risks?.length && (
                                    <ul className="list-disc space-y-1 pl-5 text-gray-400">
                                        {gem.risks.map((risk) => <li key={risk}>{risk}</li>)}
                                    </ul>
                                )}
                                {gem.invalidation && (
                                    <p className="text-xs text-gray-500">La invalidaría: {gem.invalidation}</p>
                                )}
                            </div>
                        )}
                        {gem.review_status === 'sin_revision_ia' && (
                            <div className="mt-4 border-t border-gray-700 pt-3 text-xs text-amber-400">Sin revisión IA</div>
                        )}
                    </Card>
                ))}
            </div>
        </div>
    );
}
