'use client';

import { useId, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { formatMoney } from '@/lib/format';
import type { Currency } from '@/lib/paper-trading/types';
import type { SubmitFx } from './submit';

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
    const uid = useId();
    const clientOrderId = useRef<string>(newClientOrderId());

    const [from, setFrom] = useState<Currency>('EUR');
    const [amount, setAmount] = useState('');
    const [rate, setRate] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [pending, setPending] = useState(false);

    const to: Currency = from === 'EUR' ? 'USD' : 'EUR';
    const parsedAmount = Number(amount);
    const parsedRate = Number(rate);
    const received =
        Number.isFinite(parsedAmount) && parsedAmount > 0 && Number.isFinite(parsedRate) && parsedRate > 0
            ? parsedAmount * parsedRate
            : null;

    async function onSubmit(event: React.FormEvent) {
        event.preventDefault();
        setNotice(null);
        if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) {
            setError('Indica un importe mayor que cero.');
            return;
        }
        if (!Number.isFinite(parsedRate) || parsedRate <= 0) {
            setError('Indica el tipo de cambio (simulado) mayor que cero.');
            return;
        }
        setError(null);
        setPending(true);
        try {
            const result = await submitFx({
                from,
                to,
                amountFrom: parsedAmount,
                rate: parsedRate,
                clientOrderId: clientOrderId.current,
            });
            if (result.ok) {
                setNotice('Conversión registrada en la cuenta demo.');
                clientOrderId.current = newClientOrderId();
                setAmount('');
                setRate('');
            } else {
                setError(result.error);
            }
        } finally {
            setPending(false);
        }
    }

    return (
        <form onSubmit={onSubmit} aria-label="Conversión de divisa simulada" className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-from`}>De</Label>
                    <div className="flex gap-2" role="group" aria-label="Divisa de origen">
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
                    <Label htmlFor={`${uid}-amount`}>Importe ({from})</Label>
                    <Input
                        className="placeholder:text-gray-600"
                        id={`${uid}-amount`}
                        value={amount}
                        onChange={(event) => setAmount(event.target.value)}
                        inputMode="decimal"
                        placeholder="p. ej. 1.000"
                        required
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-rate`}>
                        Tipo: 1 {from} = … {to}
                    </Label>
                    <Input
                        className="placeholder:text-gray-600"
                        id={`${uid}-rate`}
                        value={rate}
                        onChange={(event) => setRate(event.target.value)}
                        inputMode="decimal"
                        placeholder={from === 'EUR' ? 'p. ej. 1,12' : 'p. ej. 0,89'}
                        required
                    />
                </div>
            </div>

            <p className="text-xs text-gray-500">
                Conversión simulada con el tipo que introduces tú; la demo no consulta el mercado.
                {received !== null ? (
                    <>
                        {' '}
                        Recibirías <span className="font-medium text-gray-300">{formatMoney(received, to)}</span>.
                    </>
                ) : null}
            </p>

            {error ? (
                <p role="alert" className="text-sm text-red-400">
                    {error}
                </p>
            ) : null}
            {notice ? (
                <p role="status" className="text-sm text-teal-300">
                    {notice}
                </p>
            ) : null}

            <Button type="submit" variant="outline" disabled={disabled || pending}>
                {pending ? 'Registrando…' : 'Registrar conversión simulada'}
            </Button>
        </form>
    );
}
