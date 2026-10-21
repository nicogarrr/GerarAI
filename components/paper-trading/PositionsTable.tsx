import { EmptyState } from '@/components/ui/empty-state';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatMoney, formatNumber } from '@/lib/format';
import { valuationRowKey, type DemoValuation, type ValuedPosition } from '@/lib/market/demo-valuation';
import type { DemoPositionView } from './submit';

/**
 * Posiciones abiertas de la cuenta demo, derivadas del libro por FIFO.
 * Sin ajustes por splits, dividendos ni ampliaciones (limitación declarada
 * de la demo): una posición que cruce una de ellas queda descuadrada.
 */
function pnlTone(value: number | null): string {
    return value === null || value === 0 ? 'text-gray-400' : value > 0 ? 'text-teal-300' : 'text-red-400';
}

export function PositionsTable({ positions, valuation }: { positions: DemoPositionView[]; valuation?: DemoValuation | null }) {
    const valued = new Map<string, ValuedPosition>((valuation?.rows ?? []).map((row) => [valuationRowKey(row), row]));
    if (positions.length === 0) {
        return <EmptyState title="Sin posiciones abiertas" description="Las compras que registres aparecerán aquí." />;
    }
    return (
        <div className="space-y-2">
            <Table dense regionLabel="Tabla de posiciones abiertas, desplazable horizontalmente">
                <TableHeader>
                    <TableRow>
                        <TableHead>Instrumento</TableHead>
                        <TableHead className="text-right">Cantidad</TableHead>
                        <TableHead className="text-right">Coste medio</TableHead>
                        {valuation ? <TableHead className="hidden text-right md:table-cell">Valor actual</TableHead> : null}
                        {valuation ? <TableHead className="hidden text-right md:table-cell">PyG no realizada</TableHead> : null}
                        <TableHead className="text-right">Realizado</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {positions.map((position) => (
                        <TableRow key={`${position.currency}|${position.instrumentKey}`}>
                            <TableCell className="min-w-52 md:min-w-0">
                                <span className="block font-medium text-gray-100">{position.name}</span>
                                <span className="block text-xs text-gray-500">
                                    {position.kind === 'opcion' ? 'Opción' : 'Acción'} · {position.instrumentKey}
                                </span>
                                {valuation ? <MobileValuation row={valued.get(valuationRowKey(position)) ?? null} currency={position.currency} /> : null}
                            </TableCell>
                            <TableCell className="text-right">{formatNumber(position.quantity, { maximumFractionDigits: 0 })}</TableCell>
                            <TableCell className="text-right">{formatMoney(position.avgCost, position.currency)}</TableCell>
                            {valuation ? <ValuationCells row={valued.get(valuationRowKey(position)) ?? null} currency={position.currency} /> : null}
                            <TableCell
                                className={`text-right ${
                                    position.realizedPnl > 0 ? 'text-teal-300' : position.realizedPnl < 0 ? 'text-red-400' : 'text-gray-400'
                                }`}
                            >
                                {formatMoney(position.realizedPnl, position.currency)}
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
            <p className="text-xs text-gray-500">Realizado antes de comisiones (las comisiones solo mueven el efectivo). Sin ajustes por splits ni dividendos (simplificación de la demo).</p>
        </div>
    );
}

function ValuationCells({ row, currency }: { row: ValuedPosition | null; currency: DemoPositionView['currency'] }) {
    if (!row || row.status !== 'valorada' || row.marketValue === null) {
        return (
            <>
                <TableCell className="hidden text-right md:table-cell">
                    <span className="block text-gray-300">N/D</span>
                    <span className="block max-w-56 text-xs whitespace-normal text-gray-500">{row?.note ?? 'Sin valoración.'}</span>
                    {row?.quoteLabel ? <span className="block text-xs text-gray-500">{row.quoteLabel}</span> : null}
                </TableCell>
                <TableCell className="hidden text-right text-gray-400 md:table-cell">N/D</TableCell>
            </>
        );
    }
    return (
        <>
            <TableCell className="hidden text-right md:table-cell">
                <span className="block">{formatMoney(row.marketValue, currency)}</span>
                <span className="block max-w-56 text-xs whitespace-normal text-gray-500">{row.quoteLabel}</span>
            </TableCell>
            <TableCell className={`hidden text-right md:table-cell ${pnlTone(row.unrealizedPnl)}`}>
                <span className="block">{formatMoney(row.unrealizedPnl, currency)}</span>
                {row.unrealizedPct !== null ? (
                    <span className="block text-xs">{formatNumber(row.unrealizedPct, { maximumFractionDigits: 1 })} %</span>
                ) : null}
            </TableCell>
        </>
    );
}

/** En móvil las columnas de valoración se ocultan y la misma información va bajo el nombre. */
function MobileValuation({ row, currency }: { row: ValuedPosition | null; currency: DemoPositionView['currency'] }) {
    if (!row || row.status !== 'valorada' || row.marketValue === null) {
        return (
            <span className="mt-1 block text-xs whitespace-normal text-gray-400 md:hidden">
                Valor actual: N/D. {row?.note ?? 'Sin valoración.'}
                {row?.quoteLabel ? ` ${row.quoteLabel}.` : ''}
            </span>
        );
    }
    return (
        <span className="mt-1 block text-xs whitespace-normal text-gray-400 md:hidden">
            Valor {formatMoney(row.marketValue, currency)} · PyG no realizada{' '}
            <span className={pnlTone(row.unrealizedPnl)}>
                {formatMoney(row.unrealizedPnl, currency)}
                {row.unrealizedPct !== null ? ` (${formatNumber(row.unrealizedPct, { maximumFractionDigits: 1 })} %)` : ''}
            </span>
            . {row.quoteLabel}.
        </span>
    );
}
