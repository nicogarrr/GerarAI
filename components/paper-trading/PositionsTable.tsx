'use client';

import { EmptyState } from '@/components/ui/empty-state';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useT, useLocale, useFormat } from '@/lib/i18n/client';
import { valuationRowKey, type DemoValuation, type ValuedPosition } from '@/lib/market/demo-valuation';
import type { DemoPositionView } from './submit';
import type { TFunction } from '@/lib/i18n/client';
import type { Formatters } from '@/lib/i18n/format';

/**
 * Posiciones abiertas de la cuenta demo, derivadas del libro por FIFO.
 * Sin ajustes por splits, dividendos ni ampliaciones (limitación declarada
 * de la demo): una posición que cruce una de ellas queda descuadrada.
 */
/** dd/mm/yyyy desde la fecha civil del contrato, SIN crear Date: la fecha
 *  OCC es civil (Nueva York) y convertirla cambiaría el día según la tz. */
function formatContractDate(iso: string, locale: string = 'es'): string {
    const [y, m, d] = iso.split('-');
    return locale === 'en' ? `${m}/${d}/${y}` : `${d}/${m}/${y}`;
}

function pnlTone(value: number | null): string {
    return value === null || value === 0 ? 'text-gray-400' : value > 0 ? 'text-teal-300' : 'text-red-400';
}

export function PositionsTable({ positions, valuation }: { positions: DemoPositionView[]; valuation?: DemoValuation | null }) {
    const ti = useT();
    const locale = useLocale();
    const f = useFormat();
    const valued = new Map<string, ValuedPosition>((valuation?.rows ?? []).map((row) => [valuationRowKey(row), row]));
    if (positions.length === 0) {
        return <EmptyState title={ti('paperTrading.positions.emptyTitle')} description={ti('paperTrading.positions.emptyDescription')} />;
    }
    return (
        <div className="space-y-2">
            <Table dense regionLabel={ti('paperTrading.positions.regionLabel')}>
                <TableHeader>
                    <TableRow>
                        <TableHead>{ti('paperTrading.positions.colInstrument')}</TableHead>
                        <TableHead className="text-right">{ti('paperTrading.positions.colQuantity')}</TableHead>
                        <TableHead className="text-right">{ti('paperTrading.positions.colAvgCost')}</TableHead>
                        {valuation ? <TableHead className="hidden text-right md:table-cell">{ti('paperTrading.positions.colValue')}</TableHead> : null}
                        {valuation ? <TableHead className="hidden text-right md:table-cell">{ti('paperTrading.positions.colUnrealized')}</TableHead> : null}
                        <TableHead className="text-right">{ti('paperTrading.positions.colRealized')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {positions.map((position) => (
                        <TableRow key={`${position.currency}|${position.instrumentKey}`}>
                            <TableCell className="min-w-52 md:min-w-0">
                                <span className="block font-medium text-gray-100">{position.name}</span>
                                <span className="block text-xs text-gray-500">
                                    {position.kind === 'opcion' ? ti('paperTrading.positions.kindOption') : ti('paperTrading.positions.kindStock')} · {position.instrumentKey}
                                </span>
                                {position.optionBadge === 'vencida' && position.optionExpiry ? (
                                    <div className="mt-1">
                                        <span className="inline-block rounded border border-amber-800 bg-amber-950/40 px-1.5 py-0.5 text-xs text-amber-300">
                                            {ti('paperTrading.positions.expiredBadge', { date: formatContractDate(position.optionExpiry, locale) })}
                                        </span>
                                        {/* Detalle expandible nativo (details/summary: funciona con teclado
                                            y en móvil sin JS): el límite queda accesible sin ruido visual. */}
                                        <details className="mt-1 text-xs text-gray-400">
                                            <summary className="cursor-pointer select-none text-amber-300/80 underline decoration-dotted underline-offset-2">{ti('paperTrading.positions.whatMeans')}</summary>
                                            <p className="mt-1 max-w-prose">
                                                {ti('paperTrading.positions.expiredDetail')}
                                            </p>
                                        </details>
                                    </div>
                                ) : null}
                                {position.optionBadge === 'vence-hoy' && position.optionExpiry ? (
                                    <span className="mt-1 block rounded border border-amber-800 bg-amber-950/40 px-1.5 py-0.5 text-xs text-amber-300">
                                        {ti('paperTrading.positions.expiresToday', { date: formatContractDate(position.optionExpiry, locale) })}
                                    </span>
                                ) : null}
                                {valuation ? <MobileValuation row={valued.get(valuationRowKey(position)) ?? null} currency={position.currency} ti={ti} f={f} /> : null}
                            </TableCell>
                            <TableCell className="text-right">{f.formatNumber(position.quantity, { maximumFractionDigits: 0 })}</TableCell>
                            <TableCell className="text-right">{f.formatMoney(position.avgCost, position.currency)}</TableCell>
                            {valuation ? <ValuationCells row={valued.get(valuationRowKey(position)) ?? null} currency={position.currency} ti={ti} f={f} /> : null}
                            <TableCell
                                className={`text-right ${
                                    position.realizedPnl > 0 ? 'text-teal-300' : position.realizedPnl < 0 ? 'text-red-400' : 'text-gray-400'
                                }`}
                            >
                                {f.formatMoney(position.realizedPnl, position.currency)}
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
            <p className="text-xs text-gray-500">{ti('paperTrading.positions.footnote')}</p>
        </div>
    );
}

function ValuationCells({ row, currency, ti, f }: { row: ValuedPosition | null; currency: DemoPositionView['currency']; ti: TFunction; f: Formatters }) {
    if (!row || row.status !== 'valorada' || row.marketValue === null) {
        return (
            <>
                <TableCell className="hidden text-right md:table-cell">
                    <span className="block text-gray-300">{ti('paperTrading.positions.nd')}</span>
                    {/* El motivo no va solo en title/truncate (auditor 21-oct-2026):
                        expandible nativo, accesible con teclado y táctil. */}
                    <details className="mt-0.5 text-xs text-gray-500">
                        <summary className="ml-auto w-fit cursor-pointer select-none text-gray-400 underline decoration-dotted underline-offset-2">{ti('paperTrading.positions.reasonSummary')}</summary>
                        <p className="mt-1 max-w-56 whitespace-normal">{row?.note ?? ti('paperTrading.positions.noValuation')}</p>
                    </details>
                    {row?.quoteLabel ? <span className="block text-xs text-gray-500">{row.quoteLabel}</span> : null}
                </TableCell>
                <TableCell className="hidden text-right text-gray-400 md:table-cell">{ti('paperTrading.positions.nd')}</TableCell>
            </>
        );
    }
    return (
        <>
            <TableCell className="hidden text-right md:table-cell">
                <span className="block">{f.formatMoney(row.marketValue, currency)}</span>
                <span className="block max-w-56 text-xs whitespace-normal text-gray-500">{row.quoteLabel}</span>
            </TableCell>
            <TableCell className={`hidden text-right md:table-cell ${pnlTone(row.unrealizedPnl)}`}>
                <span className="block">{f.formatMoney(row.unrealizedPnl, currency)}</span>
                {row.unrealizedPct !== null ? (
                    <span className="block text-xs">{f.formatNumber(row.unrealizedPct, { maximumFractionDigits: 1 })} %</span>
                ) : null}
            </TableCell>
        </>
    );
}

/** En móvil las columnas de valoración se ocultan y la misma información va bajo el nombre. */
function MobileValuation({ row, currency, ti, f }: { row: ValuedPosition | null; currency: DemoPositionView['currency']; ti: TFunction; f: Formatters }) {
    if (!row || row.status !== 'valorada' || row.marketValue === null) {
        return (
            <span className="mt-1 block text-xs whitespace-normal text-gray-400 md:hidden">
                {ti('paperTrading.positions.mobileValueNd', { note: row?.note ?? ti('paperTrading.positions.noValuation') })}
                {row?.quoteLabel ? ` ${row.quoteLabel}.` : ''}
            </span>
        );
    }
    return (
        <span className="mt-1 block text-xs whitespace-normal text-gray-400 md:hidden">
            {ti('paperTrading.positions.mobileValue', {
                value: f.formatMoney(row.marketValue, currency),
                pnl: `${f.formatMoney(row.unrealizedPnl, currency)}${row.unrealizedPct !== null ? ` (${f.formatNumber(row.unrealizedPct, { maximumFractionDigits: 1 })} %)` : ''}`,
                quoteLabel: row.quoteLabel ?? '',
            })}
        </span>
    );
}
