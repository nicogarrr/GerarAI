import { AlertTriangle } from 'lucide-react';

import { Stat } from '@/components/ui/stat';
import { formatMoney } from '@/lib/format';
import type { AccountState, Currency } from '@/lib/paper-trading/types';

const CURRENCIES: Currency[] = ['EUR', 'USD'];

/**
 * Saldos de la cuenta demo manual: efectivo y realizado por divisa, sin
 * mezclar EUR con USD (el contrato prohibe la conversion implicita). La
 * divisa de cada cifra ES la clave del saldo, nunca una fija.
 * Las violaciones de integridad NUNCA se ocultan: si el recalculo detecta
 * una sobreventa o un sobregiro, se muestra tal cual.
 */
export function AccountSummary({ account }: { account: AccountState }) {
    return (
        <section aria-label="Saldo de la cuenta demo" className="space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {CURRENCIES.map((currency) => (
                    <Stat
                        key={`cash-${currency}`}
                        label={`Efectivo ${currency}`}
                        size="sm"
                        value={formatMoney(account.cashByCurrency[currency], currency)}
                    />
                ))}
                {CURRENCIES.map((currency) => {
                    const realized = account.realizedPnlByCurrency[currency];
                    return (
                        <Stat
                            key={`realized-${currency}`}
                            label={`Realizado ${currency}`}
                            size="sm"
                            value={formatMoney(realized, currency)}
                            tone={realized > 0 ? 'good' : realized < 0 ? 'bad' : 'default'}
                        />
                    );
                })}
            </div>
            {account.violations.length > 0 ? (
                <div
                    role="alert"
                    className="rounded-lg border border-red-800/60 bg-red-950/40 p-3 text-sm text-red-300"
                >
                    <p className="flex items-center gap-2 font-semibold">
                        <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
                        Incidencias de integridad en la cuenta demo
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-6">
                        {account.violations.map((violation) => (
                            <li key={violation}>{violation}</li>
                        ))}
                    </ul>
                </div>
            ) : null}
        </section>
    );
}
