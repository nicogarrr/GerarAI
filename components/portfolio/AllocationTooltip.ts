/**
 * Tooltip del donut de distribución. Módulo .ts sin JSX para que las
 * guardas puedan montarlo con react-dom/server y verificar el resultado
 * (moneda, ausencia de enlace y de G/P para la caja).
 */
import { createElement as h, type ReactNode } from 'react';
import Link from 'next/link.js';
// @ts-expect-error TS5097
import { formatMoney, formatPercent } from '../../lib/format.ts';
// @ts-expect-error TS5097
import { CASH_SLICE_SYMBOL, type AllocationSliceData } from '../../lib/portfolio-allocation.ts';

export type AllocationTooltipProps = {
    active?: boolean;
    payload?: Array<{ payload: AllocationSliceData }>;
    /** Moneda base de la cartera: sin ella formatMoney caería en USD. */
    currency?: string;
    /** Etiquetas localizadas; por defecto las del diccionario es. */
    labels?: { value: string; weight: string; pnl: string };
    /** Formateadores ligados al locale (useFormat en el chart). */
    f?: { formatMoney: typeof formatMoney; formatPercent: typeof formatPercent };
};

// Paridad con portfolio.allocationTooltip del diccionario es (la guarda la verifica).
const DEFAULT_LABELS = { value: 'Valor', weight: 'Peso', pnl: 'G/P' };

const line = (label: string, value: ReactNode, className = 'font-semibold text-white') =>
    h('p', { className: 'text-gray-300 text-sm' }, `${label}: `, h('span', { className }, value));

export function AllocationTooltip({ active, payload, currency, labels = DEFAULT_LABELS, f }: AllocationTooltipProps) {
    if (!active || !payload || payload.length === 0) {
        return null;
    }
    const fmtMoney = f?.formatMoney ?? formatMoney;
    const fmtPercent = f?.formatPercent ?? formatPercent;
    const data = payload[0].payload;
    const isCash = data.symbol === CASH_SLICE_SYMBOL;
    const title = isCash
        ? h('span', { className: 'font-bold text-gray-200 mb-1 block' }, CASH_SLICE_SYMBOL)
        : h(Link, { href: `/research/${data.symbol}`, className: 'font-bold text-teal-400 hover:text-teal-300 mb-1 block' }, data.symbol);
    const children: ReactNode[] = [
        title,
        line(labels.value, fmtMoney(data.value, currency)),
        line(labels.weight, fmtPercent(data.percentage, { fromRatio: false, digits: 1 })),
    ];
    if (!isCash) {
        const isPositive = data.gain >= 0;
        children.push(line(
            labels.pnl,
            fmtPercent(data.gainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' }),
            `font-semibold ${isPositive ? 'text-green-400' : 'text-red-400'}`,
        ));
    }
    return h('div', { className: 'bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-xl' }, ...children);
}
