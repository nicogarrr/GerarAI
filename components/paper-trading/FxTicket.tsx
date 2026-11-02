'use client';

import { useId, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useLocale, useT, useFormat } from '@/lib/i18n/client';
import { paperTradingMessage } from '@/lib/paper-trading/messages-en';
import { useRouter } from 'next/navigation';
import type { Currency } from '@/lib/paper-trading/types';
import { clientOrderIdAfter, parseEsNumber, type SubmitFx } from './submit';
import { invalidMessage, TicketFeedbackMessages, useExecutedAtLocal, type FieldInvalid } from './ticket-feedback';

function newClientOrderId(): string {
    return typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `fx-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Conversión EUR<->USD de la cuenta demo: operación manual simulada con el
 * tipo de cambio que introduce el usuario. No consulta ningún mercado.
 */
export function FxTicket({ submitFx, disabled }: { submitFx: SubmitFx; disabled?: boolean }) {
    const ti = useT();
    const locale = useLocale();
    const f = useFormat();
    const uid = useId();
    const router = useRouter();
    const clientOrderId = useRef<string>(newClientOrderId());

    const [from, setFrom] = useState<Currency>('EUR');
    const [amount, setAmount] = useState('');
    const [rate, setRate] = useState('');
    const [executedAtLocal, setExecutedAtLocal] = useExecutedAtLocal();
    const [invalid, setInvalid] = useState<FieldInvalid>(null);
    // Feedback del envío (rechazo/fallo de la acción): persiste hasta el próximo envío.
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [duplicate, setDuplicate] = useState<string | null>(null);
    const [pending, setPending] = useState(false);

    const fieldKey = JSON.stringify([from, amount, rate, executedAtLocal]);
    const validationError = invalidMessage(invalid, fieldKey);

    const to: Currency = from === 'EUR' ? 'USD' : 'EUR';
    const numInputHint = ti('paperTrading.numInputHint');
    const parsedAmount = parseEsNumber(amount);
    const parsedRate = parseEsNumber(rate);
    const received =
        Number.isFinite(parsedAmount) && parsedAmount > 0 && Number.isFinite(parsedRate) && parsedRate > 0
            ? parsedAmount * parsedRate
            : null;

    async function onSubmit(event: React.FormEvent) {
        event.preventDefault();
        setNotice(null);
        setDuplicate(null);
        if (!Number.isFinite(parsedAmount)) {
            setInvalid({ key: fieldKey, message: ti('paperTrading.fx.amountInvalid', { hint: numInputHint }) });
            return;
        }
        if (parsedAmount <= 0) {
            setInvalid({ key: fieldKey, message: ti('paperTrading.fx.amountPositive') });
            return;
        }
        if (!Number.isFinite(parsedRate)) {
            setInvalid({ key: fieldKey, message: ti('paperTrading.fx.rateInvalid', { hint: numInputHint }) });
            return;
        }
        if (parsedRate <= 0) {
            setInvalid({ key: fieldKey, message: ti('paperTrading.fx.ratePositive') });
            return;
        }
        const executedAt = new Date(executedAtLocal).getTime();
        if (!Number.isFinite(executedAt)) {
            setInvalid({ key: fieldKey, message: ti('paperTrading.fx.dateRequired') });
            return;
        }
        if (executedAt > Date.now()) {
            setInvalid({ key: fieldKey, message: ti('paperTrading.fx.dateFuture') });
            return;
        }
        setInvalid(null);
        setSubmitError(null);
        setPending(true);
        try {
            const result = await submitFx({
                from,
                to,
                amount: parsedAmount,
                rate: parsedRate,
                executedAt,
                clientOrderId: clientOrderId.current,
            });
            if (result.ok) {
                if (result.outcome === 'filled') {
                    setNotice(ti('paperTrading.fx.filled'));
                    setAmount('');
                    setRate('');
                    router.refresh();
                } else if (result.outcome === 'duplicate') {
                    setDuplicate(
                        result.reason
                            ? ti('paperTrading.fx.duplicateRejected', { reason: paperTradingMessage(result.reason, locale) })
                            : ti('paperTrading.fx.duplicateFill'),
                    );
                } else {
                    setSubmitError(ti('paperTrading.fx.rejected', { reason: result.reason ? paperTradingMessage(result.reason, locale) : ti('paperTrading.ticket.reasonMissing') }));
                }
                clientOrderId.current = clientOrderIdAfter(result, clientOrderId.current, newClientOrderId);
            } else {
                // Fallo desconocido (red/servidor): id CONSERVADO, reintento idempotente.
                setSubmitError(paperTradingMessage(result.error, locale));
            }
        } finally {
            setPending(false);
        }
    }

    return (
        <form onSubmit={onSubmit} aria-label={ti('paperTrading.fx.ariaLabel')} className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-from`}>{ti('paperTrading.fx.fromLabel')}</Label>
                    <div className="flex gap-2" role="group" aria-label={ti('paperTrading.fx.fromGroup')}>
                        {(['EUR', 'USD'] as const).map((value) => (
                            <Button
                                key={value}
                                type="button"
                                size="sm"
                                variant={from === value ? 'default' : 'outline'}
                                onClick={() => setFrom(value)}
                                aria-pressed={from === value}
                            >
                                {value}
                            </Button>
                        ))}
                    </div>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-amount`}>{ti('paperTrading.fx.amountLabel', { from })}</Label>
                    <Input
                        style={{ minHeight: 44 }}
                        className="placeholder:text-gray-500"
                        id={`${uid}-amount`}
                        value={amount}
                        onChange={(event) => setAmount(event.target.value)}
                        inputMode="decimal"
                        placeholder={ti('paperTrading.fx.amountPh')}
                        required
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-rate`}>
                        {ti('paperTrading.fx.rateLabel', { from, to })}
                    </Label>
                    <Input
                        style={{ minHeight: 44 }}
                        className="placeholder:text-gray-500"
                        id={`${uid}-rate`}
                        value={rate}
                        onChange={(event) => setRate(event.target.value)}
                        inputMode="decimal"
                        placeholder={from === 'EUR' ? ti('paperTrading.fx.ratePhEur') : ti('paperTrading.fx.ratePhUsd')}
                        required
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-executed`}>{ti('paperTrading.fx.dateLabel')}</Label>
                    <Input
                        style={{ minHeight: 44 }}
                        id={`${uid}-executed`}
                        type="datetime-local"
                        value={executedAtLocal}
                        onChange={(event) => setExecutedAtLocal(event.target.value)}
                        required
                    />
                </div>
            </div>

            <p className="text-xs text-gray-500">
                {ti('paperTrading.fx.formatHint')} {ti('paperTrading.fx.note')}
                {received !== null ? (
                    <>
                        {' '}
                        {ti('paperTrading.fx.receivePart', { amount: f.formatMoney(received, to) })}
                    </>
                ) : null}
            </p>

            <TicketFeedbackMessages
                validationError={validationError}
                submitError={submitError}
                notice={notice}
                duplicate={duplicate}
            />

            <Button type="submit" variant="outline" disabled={disabled || pending}>
                {pending ? ti('paperTrading.fx.submitPending') : ti('paperTrading.fx.submit')}
            </Button>
        </form>
    );
}
