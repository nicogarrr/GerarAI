'use client';

import { Coins } from 'lucide-react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

import { levelTone, type ContributionSplit } from '@/lib/plan/contribution-split';
import { useFormat, useT } from '@/lib/i18n/client';

/** «Este mes X € a POOL, Y € a UBER»: la cuota del plan repartida por nivel DCA. */
export default function ContributionSplitCard({ split }: { split: ContributionSplit | null }) {
    const t = useT();
    const f = useFormat();
    // Mismo formato que formatSplitAmount de lib/plan/contribution-split,
    // pero ligado al locale activo.
    const formatSplitAmount = (value: number, currencyCode: string | null | undefined): string => {
        const text = f.formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return currencyCode ? `${text} ${currencyCode}` : text;
    };
    const empty = !split || !split.plan_exists
        ? t('plan.split.emptyNoPlan')
        : split.status === 'no_candidates'
            ? t('plan.split.emptyNoCandidates')
            : null;
    const allocations = split?.allocations ?? [];
    const currency = split?.currency ?? null;
    const basisLabel = (basis: string): string =>
        basis === 'objetivos_ticker' ? t('plan.split.basisObjetivosTicker')
        : basis === 'posiciones_iguales' ? t('plan.split.basisPosicionesIguales')
        : basis;
    return (
        <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
            <CardHeader className="border-b border-gray-700/50 pb-4">
                <div className="flex items-center gap-3">
                    <Coins className="h-5 w-5 text-teal-400" />
                    <div>
                        <CardTitle as="h2" className="text-lg font-semibold text-gray-100">{t('plan.split.title')}</CardTitle>
                        <CardDescription className="mt-0.5 text-sm text-gray-500">
                            {split?.basis ? basisLabel(split.basis) : t('plan.split.fallbackDescription')}
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
                                        <th className="py-2 pr-4 text-right font-medium">{t('plan.split.amountColumn')}</th>
                                        <th className="py-2 pr-4 text-right font-medium">{t('plan.split.weightColumn')}</th>
                                        <th className="py-2 font-medium">{t('plan.split.levelColumn')}</th>
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
                                            <td className="py-2 pr-4 text-right tabular-nums text-gray-400">{f.formatNumber(row.share_pct, { maximumFractionDigits: 1 })} %</td>
                                            <td className={`py-2 ${levelTone(row.dca_level)}`} title={row.dca_period ? t('plan.split.periodTitle', { period: row.dca_period, status: row.dca_status ?? t('plan.split.noData') }) : undefined}>
                                                {row.reason}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        {split?.unallocated ? (
                            <p className="text-xs text-amber-300">{t('plan.split.unallocated', { amount: formatSplitAmount(split.unallocated ?? 0, currency) })}</p>
                        ) : null}
                    </>
                )}
                {split?.notes?.length ? (
                    <ul className="space-y-1 text-xs text-gray-500">
                        {split.notes.map((note) => <li key={note}>{note}</li>)}
                    </ul>
                ) : null}
                <p className="text-xs text-gray-500">{t('plan.split.weightNote')}</p>
            </CardContent>
        </Card>
    );
}
