import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatMoney, formatNumber, formatUserDateTime } from '@/lib/format';
import type { HistoryRow } from './submit';

/**
 * Historial de la cuenta demo: cada fila es una orden registrada por el
 * usuario (append-only, como el extracto de un broker). Incluye las
 * RECHAZADAS, que NUNCA se muestran como fills: sin precio y con badge
 * propio y motivo. Las ejecutadas llevan la fuente "Manual simulada" para
 * que nadie las confunda con una ejecución de mercado.
 */
export function LedgerTable({ entries }: { entries: HistoryRow[] }) {
    if (entries.length === 0) {
        return (
            <EmptyState
                title="Sin operaciones registradas"
                description="Usa el formulario de arriba para registrar tu primera operación simulada."
            />
        );
    }
    const sorted = [...entries].sort((a, b) => (b.executedAt ?? b.createdAt) - (a.executedAt ?? a.createdAt));
    return (
        <Table dense regionLabel="Tabla del historial de operaciones, desplazable horizontalmente">
            <TableHeader>
                <TableRow>
                    <TableHead>Fecha</TableHead>
                    <TableHead>Operación</TableHead>
                    <TableHead className="text-right">Cantidad</TableHead>
                    <TableHead className="text-right">Precio / importe</TableHead>
                    <TableHead>Estado</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {sorted.map((row) => {
                    const rejected = row.status === 'rejected';
                    return (
                        <TableRow key={row.clientOrderId}>
                            <TableCell className="whitespace-nowrap">
                                {formatUserDateTime(row.executedAt ?? row.createdAt)}
                            </TableCell>
                            <TableCell>
                                <span className="block font-medium text-gray-100">
                                    {row.kind === 'fx' ? row.name : row.symbol}
                                </span>
                                <span className="block text-xs text-gray-500">
                                    {row.kind === 'fx'
                                        ? `cambio a ${formatNumber(row.fillPrice, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
                                        : `${row.side === 'buy' ? 'Compra' : 'Venta'}${
                                              row.kind === 'opcion' ? (row.openClose === 'open' ? ' (abrir)' : ' (cerrar)') : ''
                                          }${!rejected && row.fee > 0 ? ` · comisión ${formatMoney(row.fee, row.currency)}` : ''}`}
                                    {rejected && row.rejectReason ? ` · ${row.rejectReason}` : ''}
                                </span>
                            </TableCell>
                            <TableCell className="text-right">
                                {formatNumber(row.quantity, { maximumFractionDigits: 2 })}
                            </TableCell>
                            <TableCell className="text-right">
                                {rejected || row.fillPrice === null ? (
                                    <span className="text-gray-500">N/D</span>
                                ) : row.kind === 'fx' ? (
                                    formatMoney(row.quantity, row.currency)
                                ) : (
                                    formatMoney(row.fillPrice, row.currency)
                                )}
                            </TableCell>
                            <TableCell>
                                {rejected ? (
                                    <Badge variant="destructive">Rechazada</Badge>
                                ) : (
                                    <Badge variant="outline">Manual simulada</Badge>
                                )}
                            </TableCell>
                        </TableRow>
                    );
                })}
            </TableBody>
        </Table>
    );
}
