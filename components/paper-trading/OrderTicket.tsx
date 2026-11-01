'use client';

import { useId, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { Label } from '@/components/ui/label';
import { useT, useFormat } from '@/lib/i18n/client';
import { useRouter } from 'next/navigation';
import type { Currency, OptionContract } from '@/lib/paper-trading/types';
import { expirationState, isRealDate } from '@/lib/paper-trading/options';
import { clientOrderIdAfter, parseEsNumber } from './submit';
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
 *
 * Guiado (Nico, 21-oct-2026): el simbolo/subyacente se busca por nombre o
 * ticker con el TickerSearchInput compartido (misma busqueda real que el
 * buscador global) y al elegir se rellenan simbolo y nombre; el resto del
 * ticket sigue manual porque registra una operacion YA ejecutada. No hay
 * selector de cadena de opciones: sin fuente gratuita verificable de
 * strikes/vencimientos, la identidad del contrato queda manual y etiquetada.
 * La divisa nunca se preselecciona desde el buscador (su exchange no es
 * prueba de divisa): el toggle manual manda.
 */
export function OrderTicket({ submitFill, disabled }: { submitFill: SubmitFill; disabled?: boolean }) {
    const ti = useT();
    const f = useFormat();
    const uid = useId();
    const router = useRouter();
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

    const [executedAtLocal, setExecutedAtLocal] = useState(() => {
        const now = new Date();
        now.setSeconds(0, 0);
        // datetime-local espera hora local sin zona
        return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
    });
    // Error de validación local ligado a los valores con los que se calculó:
    // en cuanto el usuario edita cualquier campo la clave cambia y deja de
    // mostrarse, sin efectos ni renders en cascada.
    const [invalid, setInvalid] = useState<{ key: string; message: string } | null>(null);
    // Feedback del envío (rechazo/fallo de la acción): persiste hasta el próximo envío.
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [duplicate, setDuplicate] = useState<string | null>(null);
    const [pending, setPending] = useState(false);

    // Al elegir una empresa del buscador se rellenan simbolo y nombre con la
    // identidad real del resultado. La divisa NO se preselecciona: el
    // exchange del buscador no es prueba de divisa verificada, asi que el
    // toggle manual del usuario manda siempre.
    const selectedSymbol = useRef<string | null>(null);
    function onSelectInstrument(stock: StockWithWatchlistStatus) {
        selectedSymbol.current = stock.symbol;
        setSymbol(stock.symbol);
        setName(stock.name);
    }
    // Si tras elegir se EDITA el simbolo, el nombre autocompletado ya no
    // corresponde: se limpia para no registrar una empresa con el nombre de
    // otra. El nombre escrito a mano (sin seleccion) no se toca.
    function onSymbolFieldChange(value: string) {
        if (selectedSymbol.current !== null && value !== selectedSymbol.current) {
            selectedSymbol.current = null;
            setName('');
        }
        setSymbol(value);
    }

    const fieldKey = JSON.stringify([kind, symbol, name, side, quantity, price, currency, callPut, strike, expiry, executedAtLocal]);
    const validationError = invalid !== null && invalid.key === fieldKey ? invalid.message : null;

    const parsedQuantity = parseEsNumber(quantity);
    const parsedPrice = parseEsNumber(price);
    const parsedStrike = parseEsNumber(strike);
    // Sin campo de comisión (Nico, 21-oct-2026: «comisiones, olvídate»):
    // la demo registra comisión 0 SIMULADA. El libro y las operaciones ya
    // registradas con comisión se conservan; esto no es la tarifa de
    // ningún bróker ni una afirmación de que operar sea gratis.
    const parsedFee = 0;
    const numInputHint = ti('paperTrading.numInputHint');

    const total = useMemo(() => {
        if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) return null;
        if (!Number.isFinite(parsedPrice) || parsedPrice <= 0) return null;
        // La comisión ya no es input (0 simulada fija): nada que validar.
        // El multiplicador es constante (100 en opciones), tampoco input.
        const multiplier = kind === 'opcion' ? 100 : 1;
        return parsedQuantity * parsedPrice * multiplier;
    }, [kind, parsedQuantity, parsedPrice]);

    function validate(): string | null {
        if (!symbol.trim()) return ti('paperTrading.ticket.errors.symbolRequired');
        if (!name.trim()) return ti('paperTrading.ticket.errors.nameRequired');
        if (!Number.isFinite(parsedQuantity)) return ti('paperTrading.ticket.errors.quantityInvalid', { hint: numInputHint });
        if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) return ti('paperTrading.ticket.errors.quantityInteger');
        if (!Number.isFinite(parsedPrice)) return ti('paperTrading.ticket.errors.priceInvalid', { hint: numInputHint });
        if (parsedPrice <= 0) return ti('paperTrading.ticket.errors.pricePositive');
        const executedAt = new Date(executedAtLocal).getTime();
        if (!Number.isFinite(executedAt)) return ti('paperTrading.ticket.errors.executedRequired');
        if (executedAt > Date.now()) return ti('paperTrading.ticket.errors.executedFuture');
        if (kind === 'opcion') {
            if (!Number.isFinite(parsedStrike)) return ti('paperTrading.ticket.errors.strikeInvalid', { hint: numInputHint });
            if (parsedStrike <= 0) return ti('paperTrading.ticket.errors.strikePositive');
            if (!EXPIRY_RE.test(expiry) || !isRealDate(expiry)) return ti('paperTrading.ticket.errors.expiryInvalid');
            // Misma regla que el servidor (buildOptionFill): una opción no se
            // puede ejecutar después de su vencimiento (fecha civil en Nueva
            // York, la del vencimiento OCC). El día del vencimiento SÍ se
            // admite, y registrar historia anterior al vencimiento también:
            // la comparación es contra la fecha de ejecución, no contra hoy.
            if (
                expirationState(
                    { underlying: symbol.trim().toUpperCase(), callPut, strike: parsedStrike, expiry, multiplier: 100, deliverable: 'acciones', adjusted: false },
                    executedAt,
                ).status === 'vencido'
            ) {
                return ti('paperTrading.ticket.errors.expiredContract');
            }
        }
        return null;
    }

    async function onSubmit(event: React.FormEvent) {
        event.preventDefault();
        setNotice(null);
        setDuplicate(null);
        const validation = validate();
        if (validation) {
            setInvalid({ key: fieldKey, message: validation });
            return;
        }
        setInvalid(null);
        setSubmitError(null);
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
                fee: parsedFee,
                executedAt: new Date(executedAtLocal).getTime(),
                clientOrderId: clientOrderId.current,
            });
            if (result.ok) {
                if (result.outcome === 'filled') {
                    setNotice(ti('paperTrading.ticket.filled'));
                    setQuantity('');
                    setPrice('');
                    router.refresh();
                } else if (result.outcome === 'duplicate') {
                    setDuplicate(
                        result.reason
                            ? ti('paperTrading.ticket.duplicateRejected', { reason: result.reason })
                            : ti('paperTrading.ticket.duplicateFill'),
                    );
                } else {
                    setSubmitError(ti('paperTrading.ticket.rejected', { reason: result.reason ?? ti('paperTrading.ticket.reasonMissing') }));
                }
                // Rechazo confirmado o duplicado de rechazo: id nuevo para el
                // próximo intento; duplicado de fill: id conservado (ver helper).
                clientOrderId.current = clientOrderIdAfter(result, clientOrderId.current, newClientOrderId);
            } else {
                // Fallo desconocido (red/servidor): id CONSERVADO, el reintento
                // es idempotente y no puede crear una segunda orden.
                setSubmitError(result.error);
            }
        } finally {
            setPending(false);
        }
    }

    const kindLabel = kind === 'accion' ? ti('paperTrading.ticket.unitShares') : ti('paperTrading.ticket.unitContracts');
    const sideLabel = kind === 'accion'
        ? (side === 'buy' ? ti('paperTrading.ticket.buy') : ti('paperTrading.ticket.sell'))
        : side === 'buy'
          ? ti('paperTrading.ticket.buyOpen')
          : ti('paperTrading.ticket.sellClose');
    const submitSideLabel = kind === 'accion'
        ? (side === 'buy' ? ti('paperTrading.ticket.submitSideBuy') : ti('paperTrading.ticket.submitSideSell'))
        : side === 'buy'
          ? ti('paperTrading.ticket.submitSideBuyOpen')
          : ti('paperTrading.ticket.submitSideSellClose');

    return (
        <form onSubmit={onSubmit} aria-label={ti('paperTrading.ticket.ariaLabel')} className="space-y-4">
            <div className="flex flex-wrap gap-2" role="group" aria-label={ti('paperTrading.ticket.kindGroup')}>
                {(['accion', 'opcion'] as const).map((value) => (
                    <Button
                        key={value}
                        type="button"
                        size="sm"
                        variant={kind === value ? 'default' : 'outline'}
                        onClick={() => setKind(value)}
                        aria-pressed={kind === value}
                    >
                        {value === 'accion' ? ti('paperTrading.ticket.kindStock') : ti('paperTrading.ticket.kindOption')}
                    </Button>
                ))}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-symbol`}>{kind === 'accion' ? ti('paperTrading.ticket.symbolStock') : ti('paperTrading.ticket.symbolOption')}</Label>
                    <TickerSearchInput
                        id={`${uid}-symbol`}
                        value={symbol}
                        onValueChange={onSymbolFieldChange}
                        onSelect={onSelectInstrument}
                        placeholder={kind === 'accion' ? ti('paperTrading.ticket.symbolPhStock') : ti('paperTrading.ticket.symbolPhOption')}
                        ariaLabel={kind === 'accion' ? ti('paperTrading.ticket.symbolAriaStock') : ti('paperTrading.ticket.symbolAriaOption')}
                        className="h-11 w-full bg-gray-800/50 uppercase placeholder:text-gray-500"
                        dropdownSide="bottom"
                        required
                    />
                    <p className="text-xs text-gray-500">{ti('paperTrading.ticket.searchHint')}</p>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-name`}>{ti('paperTrading.ticket.nameLabel')}</Label>
                    <Input
                        style={{ minHeight: 44 }}
                        className="placeholder:text-gray-500"
                        id={`${uid}-name`}
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        placeholder={ti('paperTrading.ticket.namePh')}
                        autoComplete="off"
                        required
                    />
                </div>
            </div>

            {kind === 'opcion' ? (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <div className="space-y-1.5">
                        <Label htmlFor={`${uid}-callput`}>{ti('paperTrading.ticket.callPutLabel')}</Label>
                        <div className="flex gap-2" role="group" aria-label={ti('paperTrading.ticket.callPutGroup')}>
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
                        <Label htmlFor={`${uid}-strike`}>{ti('paperTrading.ticket.strike')}</Label>
                        <Input
                        style={{ minHeight: 44 }}
                        className="placeholder:text-gray-500"
                            id={`${uid}-strike`}
                            value={strike}
                            onChange={(event) => setStrike(event.target.value)}
                            inputMode="decimal"
                            placeholder={ti('paperTrading.ticket.strikePh')}
                            required
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor={`${uid}-expiry`}>{ti('paperTrading.ticket.expiry')}</Label>
                        <Input
                        style={{ minHeight: 44 }}
                            className="w-full min-w-0 max-w-full px-3 placeholder:text-gray-500"
                            id={`${uid}-expiry`}
                            type="date"
                            value={expiry}
                            onChange={(event) => setExpiry(event.target.value)}
                            required
                        />
                        <p className="text-xs text-gray-500">{ti('paperTrading.ticket.expiryHint')}</p>
                    </div>
                </div>
            ) : null}

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-side`}>{ti('paperTrading.ticket.sideLabel')}</Label>
                    <div className="flex gap-2" role="group" aria-label={ti('paperTrading.ticket.sideGroup')}>
                        {(['buy', 'sell'] as const).map((value) => (
                            <Button
                                key={value}
                                type="button"
                                size="sm"
                                variant={side === value ? 'default' : 'outline'}
                                onClick={() => setSide(value)}
                                aria-pressed={side === value}
                            >
                                {value === 'buy' ? ti('paperTrading.ticket.buy') : ti('paperTrading.ticket.sell')}
                            </Button>
                        ))}
                    </div>
                </div>
                <div className="space-y-1.5">
                    {/* Label corto: «Cantidad (contratos)» envolvía a 2 líneas
                        a 390px y quedaba pegado al borde del input (QA piloto
                        21-oct-2026). La unidad va como sufijo del campo. */}
                    <Label htmlFor={`${uid}-quantity`}>{ti('paperTrading.ticket.quantity')}</Label>
                    <div className="relative">
                        <Input
                        style={{ minHeight: 44 }}
                            className="pr-20 placeholder:text-gray-500"
                            id={`${uid}-quantity`}
                            aria-describedby={`${uid}-quantity-unit`}
                            value={quantity}
                            onChange={(event) => setQuantity(event.target.value)}
                            inputMode="numeric"
                            placeholder={ti('paperTrading.ticket.quantityPh')}
                            required
                        />
                        <span id={`${uid}-quantity-unit`} className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-gray-500">{kindLabel}</span>
                    </div>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-price`}>{kind === 'opcion' ? ti('paperTrading.ticket.priceOption') : ti('paperTrading.ticket.priceStock')}</Label>
                    <Input
                        style={{ minHeight: 44 }}
                        className="placeholder:text-gray-500"
                        id={`${uid}-price`}
                        value={price}
                        onChange={(event) => setPrice(event.target.value)}
                        inputMode="decimal"
                        placeholder={ti('paperTrading.ticket.pricePh')}
                        required
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-currency`}>{ti('paperTrading.ticket.currency')}</Label>
                    <div className="flex gap-2" role="group" aria-label={ti('paperTrading.ticket.currencyGroup')}>
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

            <div className="space-y-1.5">
                <Label htmlFor={`${uid}-executed`}>{ti('paperTrading.ticket.executed')}</Label>
                {/* iOS Safari da al datetime-local un ancho intrínseco mayor
                    que la tarjeta y los min-w-0/max-w-full no bastan (fallo
                    real visto en iPhone 21-oct-2026): fila propia a una
                    columna y recorte duro con overflow-hidden como última
                    barrera. Verificación en dispositivo real pendiente. */}
                <div className="w-full overflow-hidden">
                    <Input
                        style={{ minHeight: 44 }}
                        className="w-full min-w-0 max-w-full px-3"
                        id={`${uid}-executed`}
                        type="datetime-local"
                        value={executedAtLocal}
                        onChange={(event) => setExecutedAtLocal(event.target.value)}
                        required
                    />
                </div>
            </div>

            <p className="text-xs text-gray-500">
                {ti('paperTrading.ticket.formatHint')} {ti('paperTrading.ticket.manualNote')}
            </p>

            {/* Resumen claro del coste ANTES de registrar (flujo guiado tipo
                ticket de bróker): se calcula solo con los datos introducidos,
                sin consultar mercado. Compra = coste total; venta = neto. */}
            {total !== null ? (
                <div className="rounded-lg border border-gray-700 bg-gray-900/50 p-3" aria-label={ti('paperTrading.ticket.summaryAria')}>
                    <p className="text-sm font-medium text-gray-200">{ti('paperTrading.ticket.summaryTitle')}</p>
                    <p className="mt-1 text-sm text-gray-300">
                        {sideLabel} · {f.formatNumber(parsedQuantity)} {kindLabel} × {f.formatMoney(parsedPrice, currency)}
                        {kind === 'opcion' ? ti('paperTrading.ticket.multiplierPart') : ''}
                        {parsedFee > 0 ? ti('paperTrading.ticket.feePart', { sign: side === 'buy' ? '+' : '−', fee: f.formatMoney(parsedFee, currency) }) : ''}
                    </p>
                    <p className="mt-1 text-base font-semibold text-gray-100">
                        {side === 'buy' ? ti('paperTrading.ticket.costBuy') : ti('paperTrading.ticket.costSell')}
                        {f.formatMoney(side === 'buy' ? total + parsedFee : total - parsedFee, currency)}
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                        {ti('paperTrading.ticket.summaryDisclaimer')}
                    </p>
                </div>
            ) : null}

            {validationError || submitError ? (
                <p role="alert" className="text-sm text-red-400">
                    {validationError ?? submitError}
                </p>
            ) : null}
            {notice ? (
                <p role="status" className="text-sm text-teal-300">
                    {notice}
                </p>
            ) : null}
            {duplicate ? (
                <p role="status" className="text-sm text-warn">
                    {duplicate}
                </p>
            ) : null}

            <Button type="submit" disabled={disabled || pending}>
                {pending ? ti('paperTrading.ticket.submitPending') : ti('paperTrading.ticket.submit', { side: submitSideLabel })}
            </Button>
        </form>
    );
}
