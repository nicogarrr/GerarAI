'use client';

import { useMemo, useRef, useState } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ArrowDownToLine, ArrowRightLeft, Upload } from 'lucide-react';
import type { ProPick } from '@/lib/actions/proPicks.actions';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import {
    buildMonthlySnapshot,
    diffSnapshots,
    isMonthlySnapshot,
    previousSnapshotRejection,
    monthKey,
    monthLabel,
    reasonDisplayText,
    type MonthlySnapshot,
    type RebalanceMove,
} from './monthlyRebalance';

interface MonthlyRebalanceViewProps {
    currentPicks: ProPick[];
    /** F383: 'ready' solo cuando los picks son de `strategyId`; si no, no se exporta. */
    picksStatus?: 'ready' | 'loading' | 'error';
    picksError?: string | null;
    strategyId?: string;
    strategyName?: string;
    month?: string;
}

function MoveList({
    moves,
    tone,
    showTone = true,
    emptyText,
}: {
    moves: RebalanceMove[];
    tone: 'in' | 'out';
    /** false en la selección vigente: sin mes anterior no hay «entra/sale». */
    showTone?: boolean;
    emptyText?: string;
}) {
    const t = useT();
    const locale = useLocale();
    if (moves.length === 0) {
        return <p className="text-sm text-gray-500">{emptyText ?? t('propicks.rebalance.emptyGroup')}</p>;
    }
    return (
        <ul className="space-y-3">
            {moves.map((move) => (
                <li
                    key={move.symbol}
                    className={`rounded-lg border p-3 sm:p-4 ${
                        showTone
                            ? tone === 'in'
                                ? 'border-green-700/50 bg-green-950/20'
                                : 'border-red-700/50 bg-red-950/20'
                            : 'border-gray-700/50 bg-gray-900/50'
                    }`}
                >
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-base font-bold text-gray-100">{move.symbol}</span>
                        {showTone && (
                            <Badge
                                variant="outline"
                                className={
                                    tone === 'in'
                                        ? 'border-green-500/50 text-green-300'
                                        : 'border-red-500/50 text-red-300'
                                }
                            >
                                {tone === 'in' ? t('propicks.rebalance.enters') : t('propicks.rebalance.exits')}
                            </Badge>
                        )}
                    </div>
                    <p className="mt-1 text-xs text-gray-500">{move.company}</p>
                    <p className="mt-2 text-sm leading-6 text-gray-300">{reasonDisplayText(move.reason.text, locale)}</p>
                    {move.reason.metric !== undefined && move.reason.value !== undefined && (
                        <p className="mt-1 text-[11px] text-gray-500" title={t('propicks.rebalance.verifiedTitle')}>
                            {t('propicks.rebalance.source', { metric: move.reason.metric, value: String(move.reason.value) })}
                        </p>
                    )}
                </li>
            ))}
        </ul>
    );
}

/**
 * Vista de rebalanceo mensual: diff entra/sale respecto al snapshot del mes
 * anterior con motivo trazable por valor, y descarga del snapshot JSON mensual.
 *
 * El mes anterior sale del snapshot que se cargue (botón «Cargar snapshot
 * anterior»): sin ese archivo no hay mes anterior con el que comparar, así que
 * la vista enseña la SELECCIÓN VIGENTE completa en vez de fingir un
 * rebalanceo (todo «entra» respecto a nada no es un dato de entrada).
 */
export default function MonthlyRebalanceView({
    currentPicks,
    picksStatus = 'ready',
    picksError = null,
    strategyId = 'adaptive',
    strategyName,
    month = monthKey(),
}: MonthlyRebalanceViewProps) {
    const t = useT();
    const locale = useLocale();
    const { formatNumber } = useFormat();
    const [previous, setPrevious] = useState<MonthlySnapshot | null>(null);
    const [fileError, setFileError] = useState<string | null>(null);
    const fileRef = useRef<HTMLInputElement>(null);

    const diff = useMemo(() => diffSnapshots(currentPicks, previous), [currentPicks, previous]);

    const handleFile = async (file: File | undefined) => {
        setFileError(null);
        if (!file) return;
        try {
            const parsed: unknown = JSON.parse(await file.text());
            if (!isMonthlySnapshot(parsed)) {
                setFileError(t('propicks.rebalance.notSnapshot'));
                return;
            }
            const rejection = previousSnapshotRejection(parsed, strategyId, month);
            if (rejection) {
                setFileError(
                    rejection === 'otherStrategy'
                        ? t('propicks.rebalance.rejectOtherStrategy')
                        : t('propicks.rebalance.rejectNotPrevious'),
                );
                return;
            }
            setPrevious(parsed);
        } catch {
            setFileError(t('propicks.rebalance.readError'));
        }
    };

    const downloadSnapshot = () => {
        if (picksStatus !== 'ready') return;
        const snapshot = buildMonthlySnapshot(currentPicks, strategyId, month);
        const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `propicks-${strategyId}-${snapshot.month}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    };

    return (
        <div className="space-y-4">
            <Card className="flex min-w-0 flex-col gap-4 rounded-lg border border-gray-700 bg-gray-800/50 p-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                        <ArrowRightLeft className="h-5 w-5 text-teal-400" />
                        <h3 className="text-base font-semibold text-gray-100">
                            {t('propicks.rebalance.title', { month: monthLabel(month, locale) })}
                        </h3>
                    </div>
                    <p className="mt-1 text-sm text-gray-400">
                        {strategyName ?? t('propicks.rebalance.defaultStrategy')} ·{' '}
                        {/* El recuento solo existe con los picks cargados: durante la
                            carga o el error mostrar «0 valores vigentes» se leía como
                            resultado real (Tester 6: «0 vigentes» y «Cargando...» a la
                            vez, con 9 picks en Selección IA del mismo run). */}
                        {picksStatus === 'ready'
                            ? t('propicks.rebalance.activeCount', {
                                  count: formatNumber(currentPicks.length, { maximumFractionDigits: 0 }),
                              })
                            : picksStatus === 'loading'
                              ? t('propicks.rebalance.loadingValues')
                              : t('propicks.rebalance.valuesUnavailable')}
                        {' · '}
                        {diff.hasPrevious && previous
                            ? t('propicks.rebalance.comparedWith', { month: monthLabel(previous.month, locale) })
                            : t('propicks.rebalance.noComparison')}
                    </p>
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                    <input
                        ref={fileRef}
                        type="file"
                        accept="application/json"
                        className="hidden"
                        onChange={(e) => void handleFile(e.target.files?.[0])}
                    />
                    <Button
                        variant="outline"
                        onClick={() => fileRef.current?.click()}
                        className="h-11 gap-2"
                    >
                        <Upload className="h-4 w-4" />
                        {t('propicks.rebalance.loadPrevious')}
                    </Button>
                    <Button onClick={downloadSnapshot} disabled={picksStatus !== 'ready'} className="h-11 gap-2">
                        <ArrowDownToLine className="h-4 w-4" />
                        {t('propicks.rebalance.download')}
                    </Button>
                </div>
            </Card>

            {picksStatus === 'loading' && (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-4 text-center">
                    <p className="text-sm text-gray-400">{t('propicks.rebalance.loadingPicks')}</p>
                </Card>
            )}
            {picksStatus === 'error' && (
                <Card className="rounded-lg border border-red-700 bg-red-900/20 p-4 text-center">
                    <p className="text-sm text-red-400">{picksError ?? t('propicks.rebalance.picksUnavailable')}</p>
                </Card>
            )}

            {fileError && (
                <Card className="rounded-lg border border-red-700 bg-red-900/20 p-4 text-center">
                    <p className="text-sm text-red-400">{fileError}</p>
                </Card>
            )}

            {picksStatus === 'ready' && !diff.hasPrevious && (
                <Card className="rounded-lg border border-amber-700/60 bg-amber-950/20 p-4">
                    <p className="text-sm leading-6 text-amber-200">
                        {t('propicks.rebalance.noHistory', { month: monthLabel(month, locale) })}
                    </p>
                </Card>
            )}

            {picksStatus !== 'ready' ? null : !diff.hasPrevious ? (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                    <div className="mb-3 flex flex-wrap items-center gap-2">
                        <h4 className="text-sm font-semibold text-gray-200">
                            {t('propicks.rebalance.currentSelection', { month: monthLabel(month, locale) })}
                        </h4>
                        <Badge variant="outline" className="border-gray-600 text-gray-300">
                            {formatNumber(diff.entered.length, { maximumFractionDigits: 0 })}
                        </Badge>
                    </div>
                    <p className="mb-3 text-xs leading-5 text-gray-500">
                        {t('propicks.rebalance.currentReasonsNote')}
                    </p>
                    <MoveList
                        moves={diff.entered}
                        tone="in"
                        showTone={false}
                        emptyText={t('propicks.rebalance.currentEmpty')}
                    />
                </Card>
            ) : (
                <>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                    <div className="mb-3 flex items-center gap-2">
                        <h4 className="text-sm font-semibold text-gray-200">{t('propicks.rebalance.entered')}</h4>
                        <Badge variant="outline" className="border-green-500/50 text-green-300">
                            {formatNumber(diff.entered.length, { maximumFractionDigits: 0 })}
                        </Badge>
                    </div>
                    <MoveList moves={diff.entered} tone="in" />
                </Card>
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                    <div className="mb-3 flex items-center gap-2">
                        <h4 className="text-sm font-semibold text-gray-200">{t('propicks.rebalance.exited')}</h4>
                        <Badge variant="outline" className="border-red-500/50 text-red-300">
                            {formatNumber(diff.exited.length, { maximumFractionDigits: 0 })}
                        </Badge>
                    </div>
                    <MoveList moves={diff.exited} tone="out" />
                </Card>
            </div>

            <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                <p className="text-sm text-gray-400">
                    {t('propicks.rebalance.kept', { count: formatNumber(diff.kept.length, { maximumFractionDigits: 0 }) })}
                    {diff.kept.length > 0 && (
                        <>: <span className="text-gray-300">{diff.kept.join(', ')}</span></>
                    )}
                    .
                </p>
            </Card>
                </>
            )}
        </div>
    );
}
