'use client';

import { AlertTriangle, Info } from 'lucide-react';

import { Stat } from '@/components/ui/stat';
import { useLocale, useT, useFormat } from '@/lib/i18n/client';
import { paperTradingMessage } from '@/lib/paper-trading/messages-en';
import type { Currency } from '@/lib/paper-trading/types';
import type { DemoStateView } from './submit';

/**
 * Saldos de la cuenta demo manual: efectivo y realizado por divisa, sin
 * mezclar EUR con USD (el contrato prohibe la conversion implicita). La
 * divisa de cada cifra ES la clave del saldo, nunca una fija.
 * El realizado es ANTES DE COMISIONES: el FIFO lo calcula como
 * cantidad x (precio venta - precio lote), y las comisiones solo mueven el
 * efectivo (verificado en lib/paper-trading/accounting.ts, 21-oct-2026).
 * La etiqueta lo dice junto a la cifra; no se reescribe el historico.
 * Las violaciones de integridad NUNCA se ocultan: si el recalculo detecta
 * una sobreventa o un sobregiro, se muestra tal cual.
 */
export function AccountSummary({ account }: { account: DemoStateView }) {
    const ti = useT();
    const f = useFormat();
    const locale = useLocale();
    const cash: { label: string; value: number; currency: Currency }[] = [
        { label: ti('paperTrading.account.cashEur'), value: account.cashEUR, currency: 'EUR' },
        { label: ti('paperTrading.account.cashUsd'), value: account.cashUSD, currency: 'USD' },
    ];
    const realized: { label: string; value: number; currency: Currency }[] = [
        { label: ti('paperTrading.account.realizedEur'), value: account.realizedEUR, currency: 'EUR' },
        { label: ti('paperTrading.account.realizedUsd'), value: account.realizedUSD, currency: 'USD' },
    ];
    return (
        <section aria-label={ti('paperTrading.account.ariaLabel')} className="space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {cash.map((bucket) => (
                    <Stat
                        key={bucket.label}
                        label={bucket.label}
                        size="sm"
                        value={f.formatMoney(bucket.value, bucket.currency)}
                    />
                ))}
                {realized.map((bucket) => (
                    <Stat
                        key={bucket.label}
                        label={bucket.label}
                        hint={ti('paperTrading.account.realizedHint')}
                        size="sm"
                        value={f.formatMoney(bucket.value, bucket.currency)}
                        tone={bucket.value > 0 ? 'good' : bucket.value < 0 ? 'bad' : 'default'}
                    />
                ))}
            </div>
            {account.violations.length > 0 ? (
                <div
                    role="alert"
                    className="rounded-lg border border-red-800/60 bg-red-950/40 p-3 text-sm text-red-300"
                >
                    <p className="flex items-center gap-2 font-semibold">
                        <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
                        {ti('paperTrading.account.violationsTitle')}
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-6">
                        {account.violations.map((violation) => (
                            <li key={violation}>{paperTradingMessage(violation, locale)}</li>
                        ))}
                    </ul>
                </div>
            ) : null}
            {account.notices.length > 0 ? (
                <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-sm text-gray-400">
                    <p className="flex items-center gap-2 font-semibold text-gray-300">
                        <Info className="size-4 shrink-0" aria-hidden="true" />
                        {ti('paperTrading.account.noticesTitle')}
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-6">
                        {account.notices.map((notice) => (
                            <li key={notice}>{paperTradingMessage(notice, locale)}</li>
                        ))}
                    </ul>
                </div>
            ) : null}
        </section>
    );
}
