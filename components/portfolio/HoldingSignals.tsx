'use client';

import { useEffect, useMemo, useState } from 'react';
import { getHoldingSignals } from '@/lib/actions/holding-signals.actions';
import {
    dcaLevelText,
    fairValueGapPercent,
    type HoldingSignals,
} from '@/lib/portfolio/holding-signals';
import { isValidCurrencyCode } from '@/lib/format';
import { useT, useFormat } from '@/lib/i18n/client';
import { cn } from '@/lib/utils';

const EMPTY_SIGNALS: HoldingSignals = { fairValues: {}, dca: null };

/** Pide UNA vez el nivel DCA y el valor justo de todas las posiciones visibles.
 *  null mientras carga; nunca lanza (cada mitad degrada por su cuenta). */
export function useHoldingSignals(symbols: string[]): HoldingSignals | null {
    const key = useMemo(() => Array.from(new Set(symbols.map((s) => s.toUpperCase()))).sort().join(','), [symbols]);
    // Se guarda con su clave: si cambian las posiciones, la lectura vieja no se pinta.
    const [loaded, setLoaded] = useState<{ key: string; value: HoldingSignals } | null>(null);
    useEffect(() => {
        if (!key) return;
        let cancelled = false;
        getHoldingSignals(key.split(','))
            .then((value) => {
                if (!cancelled) setLoaded({ key, value });
            })
            .catch(() => {
                if (!cancelled) setLoaded({ key, value: EMPTY_SIGNALS });
            });
        return () => {
            cancelled = true;
        };
    }, [key]);
    if (!key) return EMPTY_SIGNALS;
    return loaded?.key === key ? loaded.value : null;
}

/** Chip del nivel DCA: color de la zona del motor o «Sin nivel» gris. */
export function DcaLevelChip({ symbol, signals }: { symbol: string; signals: HoldingSignals | null }) {
    const ti = useT();
    const f = useFormat();
    if (signals === null) return <span className="text-xs text-gray-500">…</span>;
    const level = signals.dca?.[symbol.toUpperCase()] ?? null;
    const title = signals.dca === null
        ? ti('portfolio.holdingSignals.dcaInactive')
        : level
          ? ti('portfolio.holdingSignals.dcaTitle')
            + (level.signalDate ? ti('portfolio.holdingSignals.dcaTitleDate', { date: f.formatMarketDate(level.signalDate) }) : '')
            + (level.forming ? ti('portfolio.holdingSignals.dcaTitleForming') : '')
          : ti('portfolio.holdingSignals.dcaNotEvaluated');
    return (
        <span
            className={cn(
                'inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-[11px] font-semibold',
                level ? 'border-transparent' : 'border-gray-700 text-gray-500',
            )}
            style={level?.color ? { backgroundColor: level.color, color: level.fg ?? undefined } : undefined}
            title={title}
        >
            {dcaLevelText(level)}
        </span>
    );
}

/** Valor justo único con su fuente y, si la divisa cuadra, el margen frente al precio. */
export function FairValueLine({
    symbol,
    price,
    priceCurrency,
    signals,
}: {
    symbol: string;
    price: number | null;
    priceCurrency: string | null;
    signals: HoldingSignals | null;
}) {
    const ti = useT();
    const f = useFormat();
    if (signals === null) return <span className="text-xs text-gray-500">…</span>;
    const fair = signals.fairValues[symbol.toUpperCase()];
    if (!fair) return <span className="text-xs text-gray-500" title={ti('portfolio.holdingSignals.noFairValueTitle')}>{ti('portfolio.holdingSignals.noFairValue')}</span>;
    const gap = fairValueGapPercent(price, priceCurrency, fair);
    const amount = fair.currency && isValidCurrencyCode(fair.currency) ? f.formatPrice(fair.value, fair.currency) : f.formatNumber(fair.value);
    return (
        <span
            className="block text-right text-xs text-gray-300"
            title={ti('portfolio.holdingSignals.fairSource', { label: fair.label }) + (fair.asOf ? ` · ${f.formatMarketDate(fair.asOf)}` : '')}
        >
            {amount}
            {gap !== null ? (
                <span className={cn('ml-1', gap >= 0 ? 'text-good' : 'text-bad')}>
                    ({f.formatPercent(gap, { fromRatio: false, digits: 1, signDisplay: 'always' })})
                </span>
            ) : null}
            <span className="block text-[10px] text-gray-500">{fair.label}</span>
        </span>
    );
}
