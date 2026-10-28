import Link from 'next/link';

import { Panel } from '@/components/ui/panel';
import type { CompanyHoldingContext } from '@/lib/actions/portfolio.actions';
import { formatDate, formatMoney, formatNumber, formatPercent, formatPrice, isValidCurrencyCode } from '@/lib/format';

const money = (value: number | null, currency: string) =>
    value === null || !isValidCurrencyCode(currency) ? null : formatMoney(value, currency, { signDisplay: 'auto' });

/**
 * La posición real (IBKR o manual) dentro de la ficha: la tesis y la decisión
 * se leen junto a lo que de verdad tienes. Mismas cifras y avisos que Cartera
 * (coste en revisión, valoración en suspensión, divisa sin tipo de cambio);
 * nada se rellena con ceros.
 */
export function CompanyPositionPanel({ context }: { context: CompanyHoldingContext | null }) {
    if (context === null || context.status === 'not_held') return null;
    if (context.status === 'error') {
        return <Panel density="compact" title="Tu posición">
            <p className="text-sm text-amber-200" role="status">{context.message} Consulta la cartera para ver el detalle.</p>
            <Link className="mt-2 inline-flex min-h-11 items-center text-sm text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href="/portfolio">Ir a la cartera</Link>
        </Panel>;
    }
    const { holding, weightPercent, positionsAsOf } = context;
    const base = holding.baseCurrency;
    const native = holding.nativeCurrency;
    const valueKnown = !holding.valueMissing && !holding.valuationHold;
    // Coste nativo (precio medio en la divisa del valor) y coste en divisa base
    // son dos datos distintos: si solo falta el tipo de cambio histórico de una
    // compra, el coste medio sigue siendo conocido y no se rotula «desconocido».
    const nativeCostKnown = !holding.costReviewMessage && holding.avgPrice > 0;
    const costKnown = nativeCostKnown && holding.cost > 0;
    const value = valueKnown ? money(holding.value, base) : null;
    const gain = valueKnown && costKnown ? money(holding.gain, base) : null;
    const nativeGain = nativeCostKnown && !holding.valuationHold && native !== base ? money(holding.nativeGain, native) : null;
    const asOf = positionsAsOf ? formatDate(positionsAsOf) : null;
    return <Panel density="compact" description={asOf ? `Datos de tu cartera a ${asOf}.` : 'Datos de tu cartera.'} title="Tu posición">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
            <div><dt className="text-gray-500">Acciones</dt><dd className="font-semibold text-gray-100">{formatNumber(holding.quantity, { maximumFractionDigits: 6 })}</dd></div>
            <div><dt className="text-gray-500">Coste medio</dt><dd className="font-semibold text-gray-100">
                {holding.costReviewMessage ? 'En revisión' : !nativeCostKnown ? 'N/D' : isValidCurrencyCode(native) ? formatPrice(holding.avgPrice, native) : formatNumber(holding.avgPrice)}
            </dd></div>
            <div><dt className="text-gray-500">Valor</dt><dd className="font-semibold text-gray-100">{value ?? 'N/D'}</dd></div>
            <div><dt className="text-gray-500">Plusvalía latente</dt><dd className={`font-semibold ${gain === null ? 'text-gray-100' : holding.gain > 0 ? 'text-emerald-300' : holding.gain < 0 ? 'text-red-300' : 'text-gray-100'}`}>
                {gain ? `${gain} (${formatPercent(holding.gainPercent, { fromRatio: false, signDisplay: 'always' })})` : 'N/D'}
            </dd>{nativeGain ? <dd className="text-xs text-gray-400">{nativeGain} en {native}</dd> : null}</div>
            <div><dt className="text-gray-500">Peso</dt><dd className="font-semibold text-gray-100">{weightPercent === null ? 'N/D' : formatPercent(weightPercent, { fromRatio: false })}</dd>
                {weightPercent !== null ? <dd className="text-xs text-gray-400">de las posiciones con valor</dd> : null}</div>
            {holding.firstBuyDate ? <div><dt className="text-gray-500">Primera compra</dt><dd className="font-semibold text-gray-100">{formatDate(holding.firstBuyDate)}</dd></div> : null}
        </dl>
        {holding.valuationHold ? <p className="mt-3 text-xs text-amber-200" role="status">Valoración en suspensión: {holding.valuationHold.reason}</p> : null}
        {!holding.valuationHold && holding.valueMissing ? <p className="mt-3 text-xs text-amber-200" role="status">Sin valor en {base}: falta el precio o el tipo de cambio.</p> : null}
        {!nativeCostKnown && !holding.costReviewMessage ? <p className="mt-3 text-xs text-amber-200" role="status">Coste de adquisición desconocido. No se puede calcular la plusvalía.</p> : null}
        {nativeCostKnown && !costKnown ? <p className="mt-3 text-xs text-amber-200" role="status">Sin coste en {base}: falta el tipo de cambio de alguna compra. No se puede calcular la plusvalía en {base}.</p> : null}
        {holding.costReviewMessage ? <p className="mt-3 text-xs text-amber-200" role="status">{holding.costReviewMessage}</p> : null}
        <Link className="mt-2 inline-flex min-h-11 items-center text-sm text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href="/portfolio">Ver en la cartera</Link>
    </Panel>;
}
