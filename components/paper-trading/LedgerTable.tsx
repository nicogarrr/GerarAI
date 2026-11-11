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
        <Table className="block md:table" dense regionLabel={ti('paperTrading.ledger.regionLabel')}>
            <TableHeader className="hidden md:table-header-group">
                <TableRow>
                    <TableHead>{ti('paperTrading.ledger.colDate')}</TableHead>
                    <TableHead>{ti('paperTrading.ledger.colOperation')}</TableHead>
                    <TableHead className="text-right">{ti('paperTrading.ledger.colQuantity')}</TableHead>
                    <TableHead className="text-right">{ti('paperTrading.ledger.colPrice')}</TableHead>
                    <TableHead>{ti('paperTrading.ledger.colStatus')}</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody className="block space-y-3 md:table-row-group md:space-y-0">
                {sorted.map((row) => {
                    const rejected = row.status === 'rejected';
                    return (
                        <TableRow className="block rounded-lg border border-gray-800 p-3 md:table-row md:rounded-none md:p-0" key={row.clientOrderId}>
                            <TableCell className="block whitespace-normal md:table-cell md:whitespace-nowrap"><span className="block text-xs text-gray-400 md:hidden">{ti('paperTrading.ledger.colDate')}</span>
                                {f.formatUserDateTime(row.executedAt ?? row.createdAt)}
                            </TableCell>
                            <TableCell className="block whitespace-normal [overflow-wrap:anywhere] md:table-cell"><span className="block text-xs text-gray-400 md:hidden">{ti('paperTrading.ledger.colOperation')}</span>
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
                            <TableCell className="block text-left md:table-cell md:text-right"><span className="block text-xs text-gray-400 md:hidden">{ti('paperTrading.ledger.colQuantity')}</span>
                                {f.formatNumber(row.quantity, { maximumFractionDigits: 2 })}
                            </TableCell>
                            <TableCell className="block text-left md:table-cell md:text-right"><span className="block text-xs text-gray-400 md:hidden">{ti('paperTrading.ledger.colPrice')}</span>
                                {rejected || row.fillPrice === null ? (
                                    <span className="text-gray-500">{ti('paperTrading.ledger.nd')}</span>
                                ) : row.kind === 'fx' ? (
                                    f.formatMoney(row.quantity, row.currency)
                                ) : (
                                    f.formatMoney(row.fillPrice, row.currency)
                                )}
                            </TableCell>
                            <TableCell className="block md:table-cell"><span className="block text-xs text-gray-400 md:hidden">{ti('paperTrading.ledger.colStatus')}</span>
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
