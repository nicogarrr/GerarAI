'use client';

import { useId, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { formatMoney, formatNumber } from '@/lib/format';
import type { Currency, OptionContract } from '@/lib/paper-trading/types';
import type { FillSubmit, SubmitFill } from './submit';

type Kind = 'accion' | 'opcion';

const EXPIRY_RE = /^\d{4}-\d{2}-\d{2}$/;

function newClientOrderId(): string {
    return typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `order-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Ticket de la cuenta demo MANUAL: registra una operacion YA ejecutada con
 * el precio que introduce el usuario. No es un motor de ordenes: no hay
 * limite pendiente, ni cruce con el mercado, ni sesion; el fill manual no
 * equivale a una ejecucion real.
 *
 * Fase 1 opciones: solo compra para abrir / venta para cerrar, contrato
 * estandar (multiplicador 100, entrega en acciones, sin ajustados). El
 * vencimiento es la fecha civil del contrato; no afirma que hoy sea
 * negociable.
 */
export function OrderTicket({ submitFill, disabled }: { submitFill: SubmitFill; disabled?: boolean }) {
    const uid = useId();
    const clientOrderId = useRef<string>(newClientOrderId());

    const [kind, setKind] = useState<Kind>('accion');
    const [symbol, setSymbol] = useState('');
    const [name, setName] = useState('');
    const [side, setSide] = useState<'buy' | 'sell'>('buy');
    const [quantity, setQuantity] = useState('');
    const [price, setPrice] = useState('');
    const [currency, setCurrency] = useState<Currency>('EUR');
    // Opciones
    const [callPut, setCallPut] = useState<'call' | 'put'>('call');
    const [strike, setStrike] = useState('');
    const [expiry, setExpiry] = useState('');

    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [pending, setPending] = useState(false);

    const parsedQuantity = Number(quantity);
    const parsedPrice = Number(price);
    const parsedStrike = Number(strike);

    const total = useMemo(() => {
        if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) return null;
        if (!Number.isFinite(parsedPrice) || parsedPrice <= 0) return null;
        const multiplier = kind === 'opcion' ? 100 : 1;
        return parsedQuantity * parsedPrice * multiplier;
    }, [kind, parsedQuantity, parsedPrice]);

    function validate(): string | null {
        if (!symbol.trim()) return 'Indica el símbolo.';
        if (!name.trim()) return 'Indica el nombre (no hay buscador en la fase manual).';
        if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) return 'La cantidad debe ser un entero mayor que cero.';
        if (!Number.isFinite(parsedPrice) || parsedPrice <= 0) return 'El precio debe ser mayor que cero.';
        if (kind === 'opcion') {
            if (!(parsedStrike > 0)) return 'El strike debe ser mayor que cero.';
            if (!EXPIRY_RE.test(expiry)) return 'Indica el vencimiento (fecha del contrato).';
        }
        return null;
    }

    async function onSubmit(event: React.FormEvent) {
        event.preventDefault();
        setNotice(null);
        const validationError = validate();
        if (validationError) {
            setError(validationError);
            return;
        }
        setError(null);
        setPending(true);
        try {
            const openClose = side === 'buy' ? 'open' : 'close';
            const instrument: FillSubmit['instrument'] =
                kind === 'accion'
                    ? { kind: 'accion', symbol: symbol.trim().toUpperCase(), name: name.trim() }
                    : {
                          kind: 'opcion',
                          name: name.trim(),
                          contract: {
                              underlying: symbol.trim().toUpperCase(),
                              callPut,
                              strike: parsedStrike,
                              expiry,
                              multiplier: 100,
                              deliverable: 'acciones',
                              adjusted: false,
                          } satisfies OptionContract,
                      };
            const result = await submitFill({
                instrument,
                side,
                openClose,
                quantity: parsedQuantity,
                price: parsedPrice,
                currency,
                clientOrderId: clientOrderId.current,
            });
            if (result.ok) {
                setNotice('Operación registrada en la cuenta demo.');
                clientOrderId.current = newClientOrderId();
                setQuantity('');
                setPrice('');
            } else {
                setError(result.error);
            }
        } finally {
            setPending(false);
        }
    }

    const kindLabel = kind === 'accion' ? 'acciones' : 'contratos';
    const sideLabel = kind === 'accion' ? (side === 'buy' ? 'Compra' : 'Venta') : side === 'buy' ? 'Compra (abrir)' : 'Venta (cerrar)';

    return (
        <form onSubmit={onSubmit} aria-label="Registrar operación simulada" className="space-y-4">
            <div className="flex flex-wrap gap-2" role="group" aria-label="Tipo de instrumento">
                {(['accion', 'opcion'] as const).map((value) => (
                    <Button
                        key={value}
                        type="button"
                        size="sm"
                        variant={kind === value ? 'default' : 'outline'}
                        onClick={() => setKind(value)}
                        aria-pressed={kind === value}
                    >
                        {value === 'accion' ? 'Acción' : 'Opción (call/put)'}
                    </Button>
                ))}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-symbol`}>{kind === 'accion' ? 'Símbolo' : 'Subyacente'}</Label>
                    <Input
                        className="uppercase placeholder:text-gray-600"
                        id={`${uid}-symbol`}
                        value={symbol}
                        onChange={(event) => setSymbol(event.target.value)}
                        placeholder={kind === 'accion' ? 'p. ej. ASTS' : 'p. ej. AAPL'}
                        autoComplete="off"
                        required
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-name`}>Nombre</Label>
                    <Input
                        className="placeholder:text-gray-600"
                        id={`${uid}-name`}
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        placeholder="p. ej. AST SpaceMobile"
                        autoComplete="off"
                        required
                    />
                </div>
            </div>

            {kind === 'opcion' ? (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <div className="space-y-1.5">
                        <Label htmlFor={`${uid}-callput`}>Tipo</Label>
                        <div className="flex gap-2" role="group" aria-label="Call o put">
                            {(['call', 'put'] as const).map((value) => (
                                <Button
                                    key={value}
                                    type="button"
                                    size="sm"
                                    variant={callPut === value ? 'default' : 'outline'}
                                    onClick={() => setCallPut(value)}
                                    aria-pressed={callPut === value}
                                >
                                    {value === 'call' ? 'Call' : 'Put'}
                                </Button>
                            ))}
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor={`${uid}-strike`}>Strike</Label>
                        <Input
                        className="placeholder:text-gray-600"
                            id={`${uid}-strike`}
                            value={strike}
                            onChange={(event) => setStrike(event.target.value)}
                            inputMode="decimal"
                            placeholder="p. ej. 200"
                            required
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor={`${uid}-expiry`}>Vencimiento</Label>
                        <Input
                        className="placeholder:text-gray-600"
                            id={`${uid}-expiry`}
                            type="date"
                            value={expiry}
                            onChange={(event) => setExpiry(event.target.value)}
                            required
                        />
                        <p className="text-xs text-gray-500">Fecha del contrato; no implica que hoy sea negociable.</p>
                    </div>
                </div>
            ) : null}

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-side`}>Lado</Label>
                    <div className="flex gap-2" role="group" aria-label="Compra o venta">
                        {(['buy', 'sell'] as const).map((value) => (
                            <Button
                                key={value}
                                type="button"
                                size="sm"
                                variant={side === value ? 'default' : 'outline'}
                                onClick={() => setSide(value)}
                                aria-pressed={side === value}
                            >
                                {value === 'buy' ? 'Compra' : 'Venta'}
                            </Button>
                        ))}
                    </div>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-quantity`}>Cantidad ({kindLabel})</Label>
                    <Input
                        className="placeholder:text-gray-600"
                        id={`${uid}-quantity`}
                        value={quantity}
                        onChange={(event) => setQuantity(event.target.value)}
                        inputMode="numeric"
                        placeholder="p. ej. 10"
                        required
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-price`}>{kind === 'opcion' ? 'Prima por acción' : 'Precio por acción'}</Label>
                    <Input
                        className="placeholder:text-gray-600"
                        id={`${uid}-price`}
                        value={price}
                        onChange={(event) => setPrice(event.target.value)}
                        inputMode="decimal"
                        placeholder="p. ej. 40,50"
                        required
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-currency`}>Divisa</Label>
                    <div className="flex gap-2" role="group" aria-label="Divisa de la operación">
                        {(['EUR', 'USD'] as const).map((value) => (
                            <Button
                                key={value}
                                type="button"
                                size="sm"
                                variant={currency === value ? 'default' : 'outline'}
                                onClick={() => setCurrency(value)}
                                aria-pressed={currency === value}
                            >
                                {value}
                            </Button>
                        ))}
                    </div>
                </div>
            </div>

            <p className="text-xs text-gray-500">
                Registras una operación ya ejecutada con el precio que introduces tú: no es una ejecución de
                mercado. Comisión 0 por defecto: la demo no reproduce comisiones reales.
                {total !== null ? (
                    <>
                        {' '}
                        Importe estimado:{' '}
                        <span className="font-medium text-gray-300">
                            {formatMoney(total, currency)}
                            {kind === 'opcion' ? ` (${formatNumber(parsedQuantity)} × ${formatMoney(parsedPrice, currency)} × 100)` : ''}
                        </span>
                        .
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

            <Button type="submit" disabled={disabled || pending}>
                {pending ? 'Registrando…' : `Registrar ${sideLabel.toLowerCase()} simulada`}
            </Button>
        </form>
    );
}
