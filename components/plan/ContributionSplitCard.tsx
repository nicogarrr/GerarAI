import { Coins } from 'lucide-react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
    BASIS_LABELS,
    formatSplitAmount,
    levelTone,
    splitEmptyMessage,
    type ContributionSplit,
} from '@/lib/plan/contribution-split';

/** «Este mes X € a POOL, Y € a UBER»: la cuota del plan repartida por nivel DCA. */
export default function ContributionSplitCard({ split }: { split: ContributionSplit | null }) {
    const empty = splitEmptyMessage(split);
    const allocations = split?.allocations ?? [];
    const currency = split?.currency ?? null;
    return (
        <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
            <CardHeader className="border-b border-gray-700/50 pb-4">
                <div className="flex items-center gap-3">
                    <Coins className="h-5 w-5 text-teal-400" />
                    <div>
                        <CardTitle as="h2" className="text-lg font-semibold text-gray-100">Aportación de este mes</CardTitle>
                        <CardDescription className="mt-0.5 text-sm text-gray-500">
                            {split?.basis ? BASIS_LABELS[split.basis] ?? split.basis : 'Reparto de la cuota mensual por nivel DCA'}
                        </CardDescription>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
                {empty ? (
                    <p className="text-sm text-gray-500">{empty}</p>
                ) : (
                    <>
                        {split?.summary ? <p className="text-base font-medium text-gray-100">{split.summary}</p> : null}
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                                        <th className="py-2 pr-4 font-medium">Ticker</th>
                                        <th className="py-2 pr-4 text-right font-medium">Importe</th>
                                        <th className="py-2 pr-4 text-right font-medium">Peso</th>
                                        <th className="py-2 font-medium">Nivel DCA</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-800">
                                    {allocations.map((row) => (
                                        <tr key={row.ticker}>
                                            <td className="py-2 pr-4">
                                                <Link className="font-mono font-semibold text-teal-300 hover:text-teal-200" href={`/research/${encodeURIComponent(row.ticker)}`}>
                                                    {row.ticker}
                                                </Link>
                                            </td>
                                            <td className="py-2 pr-4 text-right tabular-nums text-gray-100">{formatSplitAmount(row.amount, currency)}</td>
                                            <td className="py-2 pr-4 text-right tabular-nums text-gray-400">{row.share_pct.toLocaleString('es-ES', { maximumFractionDigits: 1 })} %</td>
                                            <td className={`py-2 ${levelTone(row.dca_level)}`} title={row.dca_period ? `Mes ${row.dca_period} (${row.dca_status ?? 's/d'})` : undefined}>
                                                {row.reason}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        {split?.unallocated ? (
                            <p className="text-xs text-amber-300">Sin asignar (liquidez): {formatSplitAmount(split.unallocated, currency)}</p>
                        ) : null}
                    </>
                )}
                {split?.notes?.length ? (
                    <ul className="space-y-1 text-xs text-gray-500">
                        {split.notes.map((note) => <li key={note}>{note}</li>)}
                    </ul>
                ) : null}
                <p className="text-xs text-gray-600">4X pesa 4, 3X 3, 2X 2, 1X 1; las zonas de recorte no reciben dinero nuevo y sin nivel DCA se pesa como 1X.</p>
            </CardContent>
        </Card>
    );
}
