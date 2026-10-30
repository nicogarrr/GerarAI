'use client';

import type { PortfolioSummary } from '@/lib/actions/portfolio.actions';
import { useT, useFormat, type TFunction, type Formatters } from '@/lib/i18n/client';
import { translateWith } from '@/lib/i18n/keys';
import { dictionaries } from '@/lib/i18n/messages';
import { createFormatters } from '@/lib/i18n/format';

// Defaults en español para los tests y consumidores que no pasan ti/f.
const esT: TFunction = (key, vars) => translateWith(dictionaries.es, key, vars);
const esF: Formatters = createFormatters('es');

/** "Caja: 1 US$ = 0,8769 € (25 sept 2026) · Posiciones: ..." Tipo y fecha de cada conversion. */
export function fxBasisText(summary: PortfolioSummary, ti: TFunction = esT, f: Formatters = esF): string | null {
    const rates = summary.fxRates ?? [];
    if (!rates.length) return null;
    return rates
        .map((item) => `${item.scope === 'cash' ? ti('portfolio.breakdown.fxCash') : ti('portfolio.breakdown.fxPositions')}: 1 ${item.currency} = ${f.formatNumber(item.rate, { minimumFractionDigits: 4, maximumFractionDigits: 4 })} ${summary.baseCurrency} (${f.formatDate(item.as_of)})`)
        .join(' · ');
}

/** El saldo deudor no se netea contra la caja antes de mostrarlo. */
export function PortfolioValueBreakdown({ summary }: { summary: PortfolioSummary }) {
    const ti = useT();
    const f = useFormat();
    const { equityValue, totalValue, cash, cashAssets, marginDebt, baseCurrency, status } = summary;
    const splitAvailable = cashAssets !== undefined && marginDebt !== undefined;
    return (
        <div className="rounded-xl border border-gray-700/50 bg-gray-900/60 p-4">
            <dl className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
                <div className="min-w-0">
                    <dt className="text-sm text-gray-400">{ti('portfolio.breakdown.positionsGross')}</dt>
                    <dd className="mt-1 break-words text-lg font-semibold text-gray-100">{f.formatMoney(equityValue, baseCurrency)}</dd>
                </div>
                {splitAvailable ? <>
                    <div className="min-w-0">
                        <dt className="text-sm text-gray-400">{ti('portfolio.breakdown.cashPositive')}</dt>
                        <dd className="mt-1 break-words text-lg font-semibold text-gray-100">{f.formatMoney(cashAssets, baseCurrency)}</dd>
                    </div>
                    <div className="min-w-0">
                        <dt className="text-sm text-gray-400">{ti('portfolio.breakdown.marginDebt')}</dt>
                        <dd className={`mt-1 break-words text-lg font-semibold ${marginDebt > 0 ? 'text-amber-300' : 'text-gray-100'}`}>{f.formatMoney(marginDebt, baseCurrency)}</dd>
                    </div>
                </> : <div className="min-w-0">
                    <dt className="text-sm text-gray-400">{ti('portfolio.breakdown.cashNet')}</dt>
                    <dd className="mt-1 break-words text-lg font-semibold text-gray-100">{f.formatMoney(cash, baseCurrency)}</dd>
                </div>}
                <div className="min-w-0">
                    <dt className="text-sm text-gray-400">{ti('portfolio.breakdown.netWorth')}{status === 'incomplete_fx' ? ti('portfolio.breakdown.partialSuffix') : ''}</dt>
                    <dd className="mt-1 break-words text-xl font-bold text-white sm:text-2xl">{f.formatMoney(totalValue, baseCurrency)}</dd>
                </div>
            </dl>
            {status === 'incomplete_fx' && <p className="mt-3 text-xs text-amber-300">{ti('portfolio.breakdown.incompleteFx')}</p>}
        </div>
    );
}
