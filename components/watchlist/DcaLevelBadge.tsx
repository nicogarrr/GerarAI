'use client';

import { useRef, useState } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { DcaSignalItem } from '@/lib/dca/types';
import { DCA_STATUS_LABEL, dcaDataAge, dcaMissingBadge, dcaPrice, dcaRsi, dcaSignalMetric } from '@/lib/dca/format';

interface DcaLevelBadgeProps {
    item: DcaSignalItem | undefined;
    signalMonths: number | null;
    /** Sin estado evaluado: compacto no pinta nada, completo dice «Sin evaluar», «Omitido» o «Evaluación fallida». */
    compact?: boolean;
}

/** Badge del nivel DCA con el color de su zona y el detalle en el tooltip. */
export default function DcaLevelBadge({ item, signalMonths, compact = false }: DcaLevelBadgeProps) {
    // Un tooltip solo abre con hover/foco: en el móvil el toque no enseñaba la
    // zona ni los cierres que activarían 2X-4X. El toque lo abre y lo cierra.
    const [open, setOpen] = useState(false);
    const triggerRef = useRef<HTMLButtonElement>(null);
    const state = item?.state ?? null;
    if (!state) {
        if (compact) return null;
        const missing = dcaMissingBadge(item);
        const tone =
            missing.tone === 'error'
                ? 'border-red-800 text-red-300'
                : missing.tone === 'warn'
                  ? 'border-amber-800 text-amber-300'
                  : 'border-gray-700 text-gray-500';
        return (
            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${tone}`} title={missing.title} data-testid="dca-missing-badge">
                {missing.text}
            </span>
        );
    }
    const forming = state.status === 'forming';
    const stale = state.stale === true;
    const age = dcaDataAge(state.data_age_days);
    const staleText = stale ? (age ? `desactualizado · ${age}` : 'desactualizado') : null;
    const metric = dcaSignalMetric(state, signalMonths);
    const rsi = dcaRsi(state.metrics?.rsi);
    const close = dcaPrice(state.close, state.currency_label);
    const prices = (['2x', '3x', '4x'] as const)
        .map((key) => ({ key, value: dcaPrice(state.level_prices?.[key], state.currency_label) }))
        .filter((entry) => entry.value);
    const badge = (
        <Tooltip open={open} onOpenChange={setOpen}>
            <TooltipTrigger asChild>
                <button
                    type="button"
                    ref={triggerRef}
                    aria-expanded={open}
                    // preventDefault evita que Radix cierre el tooltip en pointerdown/click.
                    onPointerDown={(event) => event.preventDefault()}
                    onClick={(event) => { event.preventDefault(); setOpen((value) => !value); }}
                    className="inline-flex min-h-6 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap"
                    style={{ backgroundColor: state.color, color: state.fg, borderColor: state.color === '#FFFFFF' ? '#9CA3AF' : state.color }}
                    aria-label={`${item?.symbol ?? ''}: ${state.label}, ${DCA_STATUS_LABEL[state.status] ?? state.status}${staleText ? `, ${staleText}` : ''}`}
                >
                    {state.label}
                    {forming ? <span aria-hidden="true" className="opacity-70">·</span> : null}
                </button>
            </TooltipTrigger>
            <TooltipContent
                side="bottom"
                // Tocar el propio badge lo cierra con su onClick, no como «fuera».
                onPointerDownOutside={(event) => { if (triggerRef.current?.contains(event.target as Node)) event.preventDefault(); }}
            >
                <p className="font-semibold">{state.zone}</p>
                <p>Estado: mes {DCA_STATUS_LABEL[state.status] ?? state.status} ({state.period})</p>
                {close ? <p>Cierre asentado: {close} · {state.signal_date}</p> : null}
                {metric ? <p>{metric.label}: {metric.value}</p> : null}
                {rsi ? <p>RSI mensual: {rsi}</p> : null}
                {prices.length > 0 ? (
                    <p>Cierre que activaría: {prices.map((entry) => `${entry.key.toUpperCase()} ${entry.value}`).join(' · ')}</p>
                ) : null}
                {forming ? <p className="text-gray-400">El mes no ha cerrado: el veredicto puede cambiar.</p> : null}
                {stale ? (
                    <p className="text-amber-300">
                        Datos desactualizados{age ? ` (último cierre ${age})` : ''}: el nivel puede no ser el actual.
                    </p>
                ) : null}
                <p className="text-gray-500">Apoyo a la decisión, no asesoramiento financiero.</p>
            </TooltipContent>
        </Tooltip>
    );
    if (!staleText) return badge;
    return (
        <span className="inline-flex max-w-full flex-wrap items-center gap-1">
            {badge}
            <span data-testid="dca-stale" className="text-[10px] leading-tight text-amber-400 whitespace-nowrap">
                {staleText}
            </span>
        </span>
    );
}
