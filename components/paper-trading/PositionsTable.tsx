import { EmptyState } from '@/components/ui/empty-state';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatMoney, formatNumber } from '@/lib/format';
import type { DemoPositionView } from './submit';

/**
 * Posiciones abiertas de la cuenta demo, derivadas del libro por FIFO.
 * Sin ajustes por splits, dividendos ni ampliaciones (limitación declarada
 * de la demo): una posición que cruce una de ellas queda descuadrada.
 */
export function PositionsTable({ positions }: { positions: DemoPositionView[] }) {
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
                        <TableHead className="text-right">Realizado</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {positions.map((position) => (
                        <TableRow key={position.instrumentKey}>
                            <TableCell>
                                <span className="block font-medium text-gray-100">{position.name}</span>
                                <span className="block text-xs text-gray-500">
                                    {position.kind === 'opcion' ? 'Opción' : 'Acción'} · {position.instrumentKey}
                                </span>
                            </TableCell>
                            <TableCell className="text-right">{formatNumber(position.quantity, { maximumFractionDigits: 0 })}</TableCell>
                            <TableCell className="text-right">{formatMoney(position.avgCost, position.currency)}</TableCell>
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
            <p className="text-xs text-gray-500">Sin ajustes por splits ni dividendos (simplificación de la demo).</p>
        </div>
    );
}
