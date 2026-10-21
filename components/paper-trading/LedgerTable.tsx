import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatMoney, formatNumber, formatUserDateTime } from '@/lib/format';
import type { Fill, FxConversion, LedgerEntry } from '@/lib/paper-trading/types';

function isFx(entry: LedgerEntry): entry is FxConversion {
    return 'kind' in entry && entry.kind === 'fx';
}

function instrumentLabel(fill: Fill): string {
    if (fill.instrument.kind === 'accion') return fill.instrument.symbol;
    const c = fill.instrument.contract;
    return `${c.underlying} ${c.callPut === 'call' ? 'C' : 'P'}${c.strike} ${c.expiry}`;
}

/**
 * Historial de la cuenta demo: cada fila es una operacion ejecutada y
 * registrada por el usuario (append-only, como el extracto de un broker).
 * La fuente SIEMPRE es manual simulada; se etiqueta en cada fila para que
 * nadie la confunda con una ejecucion de mercado.
 */
export function LedgerTable({ entries }: { entries: LedgerEntry[] }) {
    if (entries.length === 0) {
        return (
            <EmptyState
                title="Sin operaciones registradas"
                description="Usa el formulario de arriba para registrar tu primera operación simulada."
            />
        );
    }
    const sorted = [...entries].sort((a, b) => b.executedAt - a.executedAt);
    return (
        <Table dense regionLabel="Tabla del historial de operaciones, desplazable horizontalmente">
            <TableHeader>
                <TableRow>
                    <TableHead>Fecha</TableHead>
                    <TableHead>Operación</TableHead>
                    <TableHead className="text-right">Cantidad</TableHead>
                    <TableHead className="text-right">Precio / importe</TableHead>
                    <TableHead>Fuente</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {sorted.map((entry) => (
                    <TableRow key={entry.clientOrderId}>
                        <TableCell className="whitespace-nowrap">{formatUserDateTime(entry.executedAt)}</TableCell>
                        {isFx(entry) ? (
                            <>
                                <TableCell>
                                    <span className="block font-medium text-gray-100">
                                        Cambio {entry.from} → {entry.to}
                                    </span>
                                    <span className="block text-xs text-gray-500">
                                        {formatMoney(entry.amountFrom, entry.from)} a {formatNumber(entry.rate, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                                    </span>
                                </TableCell>
                                <TableCell className="text-right">—</TableCell>
                                <TableCell className="text-right">
                                    <span className="block">{formatMoney(entry.amountFrom * entry.rate, entry.to)}</span>
                                    <span className="block text-xs text-gray-500">recibido</span>
                                </TableCell>
                            </>
                        ) : (
                            <>
                                <TableCell>
                                    <span className="block font-medium text-gray-100">{instrumentLabel(entry)}</span>
                                    <span className="block text-xs text-gray-500">
                                        {entry.side === 'buy' ? 'Compra' : 'Venta'}
                                        {entry.instrument.kind === 'opcion'
                                            ? entry.openClose === 'open'
                                                ? ' (abrir)'
                                                : ' (cerrar)'
                                            : ''}
                                        {entry.fee > 0 ? ` · comisión ${formatMoney(entry.fee, entry.currency)}` : ''}
                                    </span>
                                </TableCell>
                                <TableCell className="text-right">{formatNumber(entry.quantity, { maximumFractionDigits: 0 })}</TableCell>
                                <TableCell className="text-right">{formatMoney(entry.price, entry.currency)}</TableCell>
                            </>
                        )}
                        <TableCell>
                            <Badge variant="outline">Manual simulada</Badge>
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    );
}
