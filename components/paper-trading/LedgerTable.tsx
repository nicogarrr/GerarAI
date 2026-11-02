'use client';

import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useLocale, useT, useFormat } from '@/lib/i18n/client';
import { paperTradingMessage } from '@/lib/paper-trading/messages-en';
import type { HistoryRow } from './submit';

/**
 * Historial de la cuenta demo: cada fila es una orden registrada por el
 * usuario (append-only, como el extracto de un broker). Incluye las
 * RECHAZADAS, que NUNCA se muestran como fills: sin precio y con badge
 * propio y motivo. Las ejecutadas llevan la fuente "Manual simulada" para
 * que nadie las confunda con una ejecución de mercado.
 */
export function LedgerTable({ entries }: { entries: HistoryRow[] }) {
    const ti = useT();
    const f = useFormat();
    const locale = useLocale();
    if (entries.length === 0) {
        return (
            <EmptyState
                title={ti('paperTrading.ledger.emptyTitle')}
                description={ti('paperTrading.ledger.emptyDescription')}
            />
        );
    }
    const sorted = [...entries].sort((a, b) => (b.executedAt ?? b.createdAt) - (a.executedAt ?? a.createdAt));
    return (
        <Table dense regionLabel={ti('paperTrading.ledger.regionLabel')}>
            <TableHeader>
                <TableRow>
                    <TableHead>{ti('paperTrading.ledger.colDate')}</TableHead>
                    <TableHead>{ti('paperTrading.ledger.colOperation')}</TableHead>
                    <TableHead className="text-right">{ti('paperTrading.ledger.colQuantity')}</TableHead>
                    <TableHead className="text-right">{ti('paperTrading.ledger.colPrice')}</TableHead>
                    <TableHead>{ti('paperTrading.ledger.colStatus')}</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {sorted.map((row) => {
                    const rejected = row.status === 'rejected';
                    return (
                        <TableRow key={row.clientOrderId}>
                            <TableCell className="whitespace-nowrap">
                                {f.formatUserDateTime(row.executedAt ?? row.createdAt)}
                            </TableCell>
                            <TableCell>
                                <span className="block font-medium text-gray-100">
                                    {row.kind === 'fx' ? row.name : row.symbol}
                                </span>
                                <span className="block text-xs text-gray-500">
                                    {row.kind === 'fx'
                                        ? ti('paperTrading.ledger.fxChange', { rate: f.formatNumber(row.fillPrice, { minimumFractionDigits: 2, maximumFractionDigits: 4 }) })
                                        : `${row.side === 'buy' ? ti('paperTrading.ledger.sideBuy') : ti('paperTrading.ledger.sideSell')}${
                                              row.kind === 'opcion' ? ` ${ti(row.openClose === 'open' ? 'paperTrading.ledger.open' : 'paperTrading.ledger.close')}` : ''
                                          }${!rejected && row.fee > 0 ? ti('paperTrading.ledger.feePart', { fee: f.formatMoney(row.fee, row.currency) }) : ''}`}
                                    {rejected && row.rejectReason ? ` · ${paperTradingMessage(row.rejectReason, locale)}` : ''}
                                </span>
                            </TableCell>
                            <TableCell className="text-right">
                                {f.formatNumber(row.quantity, { maximumFractionDigits: 2 })}
                            </TableCell>
                            <TableCell className="text-right">
                                {rejected || row.fillPrice === null ? (
                                    <span className="text-gray-500">{ti('paperTrading.ledger.nd')}</span>
                                ) : row.kind === 'fx' ? (
                                    f.formatMoney(row.quantity, row.currency)
                                ) : (
                                    f.formatMoney(row.fillPrice, row.currency)
                                )}
                            </TableCell>
                            <TableCell>
                                {rejected ? (
                                    <Badge variant="destructive">{ti('paperTrading.ledger.rejectedBadge')}</Badge>
                                ) : (
                                    <Badge variant="outline">{ti('paperTrading.ledger.manualBadge')}</Badge>
                                )}
                            </TableCell>
                        </TableRow>
                    );
                })}
            </TableBody>
        </Table>
    );
}
