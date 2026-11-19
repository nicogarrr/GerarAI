'use client';

import { useId, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { Label } from '@/components/ui/label';
import { useLocale, useT, useFormat } from '@/lib/i18n/client';
import { paperTradingMessage, paperTradingReason } from '@/lib/paper-trading/messages-en';
import { useRouter } from 'next/navigation';
import { instrumentKey, type Currency, type OptionContract } from '@/lib/paper-trading/types';
import { expirationState, isRealDate } from '@/lib/paper-trading/options';
import { clientOrderIdAfter, parseEsNumber } from './submit';
import { invalidMessage, TicketFeedbackMessages, useExecutedAtLocal, type FieldInvalid } from './ticket-feedback';
import type { DemoStateView, FillSubmit, SubmitFill } from './submit';
import type { DemoOptionChainOk, DemoOptionChainResult } from '@/lib/paper-trading/option-chain-view';

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
 * ticket sigue manual porque registra una operacion YA ejecutada.
 * Selector guiado de contrato de opción: con la cadena REAL diferida de
 * CBOE (>= 15 min, vía la acción demo-option-chain) el usuario elige
 * vencimiento y strike de contratos listados de verdad; la última
 * operación del contrato se muestra como referencia ETIQUETADA (nunca
 * como precio actual: el precio de la orden lo escribe el usuario) y la
 * vía manual queda siempre disponible. La divisa nunca se preselecciona
 * desde el buscador (su exchange no es prueba de divisa): el toggle
 * manual manda.
 *
 * Guiado con datos REALES de la cuenta (prop `account`, del servidor): el
 * ticket muestra el saldo disponible en la divisa elegida y, cuando el
 * instrumento ya es identificable (símbolo, y en opciones strike +
 * vencimiento válidos), la posición abierta EN ESA DIVISA — como el ticket
 * de un bróker, para no descubrir un rechazo al enviar. La validación de
 * saldo/posición sigue siendo solo del servidor; esto es información, no
 * una barrera. Sin `account` no se muestra nada (nunca se inventa).
 */
export function OrderTicket({ submitFill, disabled, account = null, fetchOptionChain = null }: { submitFill: SubmitFill; disabled?: boolean; account?: DemoStateView | null; fetchOptionChain?: ((underlying: string) => Promise<DemoOptionChainResult>) | null }) {
    const ti = useT();
    const locale = useLocale();
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

    // Selector guiado de contrato (cadena CBOE diferida): solo consulta a
    // petición del usuario; un error nunca bloquea la vía manual.
    const [chain, setChain] = useState<DemoOptionChainOk | null>(null);
    const [chainError, setChainError] = useState<string | null>(null);
    const [chainLoading, setChainLoading] = useState(false);

    const [executedAtLocal, setExecutedAtLocal] = useExecutedAtLocal();
    const [invalid, setInvalid] = useState<FieldInvalid>(null);
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
        // La cadena cargada era del subyacente anterior: se descarta.
        setChain(null);
        setChainError(null);
    }
    // Si tras elegir se EDITA el simbolo, el nombre autocompletado ya no
    // corresponde: se limpia para no registrar una empresa con el nombre de
    // otra. El nombre escrito a mano (sin seleccion) no se toca.
    function onSymbolFieldChange(value: string) {
        if (selectedSymbol.current !== null && value !== selectedSymbol.current) {
            selectedSymbol.current = null;
            setName('');
        }
        setChain(null);
        setChainError(null);
        setSymbol(value);
    }

    // Razón de fallo -> texto i18n con claves LITERALES (el checker de uso
    // i18n no sigue claves compuestas en runtime).
    function chainErrorMessage(ti: ReturnType<typeof useT>, reason: string): string {
        switch (reason) {
            case 'invalidSymbol': return ti('paperTrading.ticket.chainError.invalidSymbol');
            case 'notCovered': return ti('paperTrading.ticket.chainError.notCovered');
            case 'saturated': return ti('paperTrading.ticket.chainError.saturated');
            case 'noAuth': return ti('paperTrading.ticket.chainError.noAuth');
            default: return ti('paperTrading.ticket.chainError.sourceUnavailable');
        }
    }

    async function onLoadChain() {
        if (!fetchOptionChain || chainLoading) return;
        setChainLoading(true);
        setChainError(null);
        try {
            const result = await fetchOptionChain(symbol);
            if (result.ok) {
                setChain(result);
            } else {
                setChain(null);
                setChainError(chainErrorMessage(ti, result.reason));
            }
        } catch {
            setChain(null);
            setChainError(ti('paperTrading.ticket.chainError.sourceUnavailable'));
        } finally {
            setChainLoading(false);
        }
    }

    // ¿Cubre la cadena cargada el subyacente del ticket? Si el usuario edita
    // el símbolo tras consultar, la cadena se descarta; este candado evita
    // además juzgar un contrato contra la cadena de OTRO subyacente.
    const chainCoversSymbol = chain !== null && chain.underlying === symbol.trim().toUpperCase();

    // Referencia de la última operación del contrato elegido (si la cadena
    // la registra). Es dato DIFERIDO de CBOE, nunca el precio actual.
    // chainListed: false = el par vencimiento/strike NO aparece en la muestra
    // consultada (aviso, no error: puede existir fuera de los vencimientos
    // mostrados o haberse escrito a mano).
    const { chainRef, chainListed } = (() => {
        if (!chainCoversSymbol || !chain || !expiry) return { chainRef: undefined, chainListed: undefined };
        const parsed = parseEsNumber(strike);
        if (!Number.isFinite(parsed)) return { chainRef: undefined, chainListed: undefined };
        const row = chain.expiries.find((e) => e.expiry === expiry)?.strikes.find((r) => r.strike === parsed);
        if (!row) return { chainRef: undefined, chainListed: false };
        return { chainRef: row[callPut], chainListed: true };
    })();

    const fieldKey = JSON.stringify([kind, symbol, name, side, quantity, price, currency, callPut, strike, expiry, executedAtLocal]);
    const validationError = invalidMessage(invalid, fieldKey);

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
                            ? ti('paperTrading.ticket.duplicateRejected', { reason: paperTradingReason(result.reason, locale) })
                            : ti('paperTrading.ticket.duplicateFill'),
                    );
                } else {
                    setSubmitError(ti('paperTrading.ticket.rejected', { reason: result.reason ? paperTradingReason(result.reason, locale) : ti('paperTrading.ticket.reasonMissing') }));
                }
                // Rechazo confirmado o duplicado de rechazo: id nuevo para el
                // próximo intento; duplicado de fill: id conservado (ver helper).
                clientOrderId.current = clientOrderIdAfter(result, clientOrderId.current, newClientOrderId);
            } else {
                // Fallo desconocido (red/servidor): id CONSERVADO, el reintento
                // es idempotente y no puede crear una segunda orden.
                setSubmitError(paperTradingMessage(result.error, locale));
            }
        } finally {
            setPending(false);
        }
    }

    const kindLabel = kind === 'accion' ? ti('paperTrading.ticket.unitShares') : ti('paperTrading.ticket.unitContracts');

    // Guiado con datos reales de la cuenta (ver cabecera): saldo en la
    // divisa elegida y posición abierta del instrumento EN ESA DIVISA. La
    // clave se construye con el instrumentKey compartido (misma forma que el
    // libro), solo cuando el instrumento ya es identificable: símbolo en
    // acciones; símbolo + strike válido + vencimiento real en opciones.
    const guidance = useMemo(() => {
        if (!account) return null;
        const cash = currency === 'EUR' ? account.cashEUR : account.cashUSD;
        const trimmed = symbol.trim().toUpperCase();
        let key: string | null = null;
        if (trimmed) {
            if (kind === 'accion') {
                key = instrumentKey({ kind: 'accion', symbol: trimmed, name: '' });
            } else if (Number.isFinite(parsedStrike) && parsedStrike > 0 && EXPIRY_RE.test(expiry) && isRealDate(expiry)) {
                key = instrumentKey({
                    kind: 'opcion',
                    contract: { underlying: trimmed, callPut, strike: parsedStrike, expiry, multiplier: 100, deliverable: 'acciones', adjusted: false },
                    name: '',
                });
            }
        }
        const position = key ? account.positions.find((p) => p.instrumentKey === key && p.currency === currency) : undefined;
        return { cash, key, position };
    }, [account, currency, symbol, kind, parsedStrike, expiry, callPut]);
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
                <>
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
                {fetchOptionChain ? (
                    <div className="space-y-2 rounded-lg border border-gray-800 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-xs text-gray-400">{ti('paperTrading.ticket.chainHint')}</p>
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={chainLoading || !symbol.trim()}
                                onClick={onLoadChain}
                            >
                                {chainLoading ? ti('paperTrading.ticket.chainLoading') : ti('paperTrading.ticket.chainLoad')}
                            </Button>
                        </div>
                        {chainError ? <p className="text-xs text-amber-400">{chainError}</p> : null}
                        {chain ? (
                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-1.5">
                                    <Label htmlFor={`${uid}-chain-expiry`}>{ti('paperTrading.ticket.chainExpiry')}</Label>
                                    <select
                                        id={`${uid}-chain-expiry`}
                                        className="w-full rounded-md border border-gray-800 bg-transparent px-2 text-base sm:text-sm"
                                        style={{ minHeight: 44 }}
                                        value={chain.expiries.some((e) => e.expiry === expiry) ? expiry : ''}
                                        onChange={(event) => setExpiry(event.target.value)}
                                    >
                                        <option value="" disabled>{ti('paperTrading.ticket.chainExpiryPh')}</option>
                                        {chain.expiries.map((e) => (
                                            <option key={e.expiry} value={e.expiry}>{e.expiry}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor={`${uid}-chain-strike`}>{ti('paperTrading.ticket.chainStrike')}</Label>
                                    <select
                                        id={`${uid}-chain-strike`}
                                        className="w-full rounded-md border border-gray-800 bg-transparent px-2 text-base sm:text-sm"
                                        style={{ minHeight: 44 }}
                                        value={(() => {
                                            const strikes = chain.expiries.find((e) => e.expiry === expiry)?.strikes ?? [];
                                            return strikes.some((r) => String(r.strike) === strike) ? strike : '';
                                        })()}
                                        onChange={(event) => {
                                            if (event.target.value) setStrike(event.target.value);
                                        }}
                                    >
                                        <option value="" disabled>{ti('paperTrading.ticket.chainStrikePh')}</option>
                                        {(chain.expiries.find((e) => e.expiry === expiry)?.strikes ?? chain.expiries[0]?.strikes ?? []).map((r) => (
                                            <option key={r.strike} value={String(r.strike)}>{r.strike}</option>
                                        ))}
                                    </select>
                                </div>
                                <p className="col-span-2 text-xs text-gray-500">
                                    {ti('paperTrading.ticket.chainFetchedAt', { time: new Date(chain.fetchedAt).toLocaleTimeString(locale) })}
                                </p>
                                {chainListed === false ? (
                                    <p className="col-span-2 text-xs text-amber-400">{ti('paperTrading.ticket.chainNotListed')}</p>
                                ) : null}
                                {chainRef !== undefined ? (
                                    <p className="col-span-2 text-xs text-gray-500">
                                        {chainRef
                                            ? ti('paperTrading.ticket.chainRefTrade', { price: chainRef.price, time: chainRef.time.replace('T', ' ') })
                                            : ti('paperTrading.ticket.chainNoTrade')}
                                    </p>
                                ) : null}
                            </div>
                        ) : null}
                    </div>
                ) : null}
                </>
            ) : null}

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="space-y-1.5">
                    <Label htmlFor={`${uid}-side`}>{ti('paperTrading.ticket.sideLabel')}</Label>
                    {/* flex-1 + px-2: a 4 columnas (sm:) la celda es estrecha;
                        sin esto Compra/Venta desbordaban e invadian Cantidad
                        (QA Release 19-nov-2026). */}
                    <div className="flex gap-2" role="group" aria-label={ti('paperTrading.ticket.sideGroup')}>
                        {(['buy', 'sell'] as const).map((value) => (
                            <Button
                                key={value}
                                type="button"
                                size="sm"
                                className="min-w-0 flex-1 px-2"
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

            {guidance ? (
                // Guiado con datos reales de la cuenta (no es validación: el
                // servidor decide). El saldo siempre; la posición cuando el
                // instrumento ya es identificable, y EN LA DIVISA elegida:
                // una posición en otra divisa no sirve para cerrar aquí.
                <p className="text-xs text-gray-500">
                    {ti('paperTrading.ticket.guidanceCash', { cash: f.formatMoney(guidance.cash, currency) })}
                    {guidance.key
                        ? ` · ${guidance.position
                              ? ti('paperTrading.ticket.guidancePosition', {
                                    currency,
                                    quantity: f.formatNumber(guidance.position.quantity, { maximumFractionDigits: 0 }),
                                    unit: kindLabel,
                                })
                              : ti('paperTrading.ticket.guidanceNoPosition', { currency })}`
                        : ''}
                </p>
            ) : null}

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

            <TicketFeedbackMessages
                validationError={validationError}
                submitError={submitError}
                notice={notice}
                duplicate={duplicate}
            />

            <Button type="submit" disabled={disabled || pending}>
                {pending ? ti('paperTrading.ticket.submitPending') : ti('paperTrading.ticket.submit', { side: submitSideLabel })}
            </Button>
        </form>
    );
}
