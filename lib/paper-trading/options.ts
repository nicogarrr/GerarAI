/**
 * Opciones de la demo manual: reglas PURAS (sin BD, sin red, sin reloj
 * implicito). Consume SOLO los tipos de ./types (frontera compartida).
 *
 * Alcance fase 1 (honesto, no equivale a IBKR):
 * - Solo opciones estandar sobre acciones: multiplicador 100, entrega de
 *   acciones. Los contratos ajustados se RECHAZAN (OCC cambia deliverable y
 *   simbolo al ajustar; aqui no se modelan).
 * - Solo comprar para abrir (buy/open) y vender para cerrar (sell/close).
 *   Sin vender para abrir (cortos), sin margen, sin spreads.
 * - El precio de un fill es la prima por accion INTRODUCIDA por el usuario
 *   (source 'manual-simulado'). Nada aqui inventa una cotizacion.
 * - Vencimiento: sin ejercicio ni asignacion automaticos. Una opcion ITM al
 *   vencer queda 'pendiente-liquidacion' (el cierre se registra a mano);
 *   OTM o sin valor intrinseco, 'sin-valor'. Sin precio del subyacente,
 *   'pendiente-liquidacion' con motivo: nunca se asume.
 * - Fuentes: OCC (estandar = 100 acciones, americana, vencimiento):
 *   https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications
 */
import type { Currency, Fill, OptionContract } from './types';

export const STANDARD_MULTIPLIER = 100;
/** Maximo de decimales aceptados en la prima (tick real 0,01/0,05; margen para 4). */
const MAX_PREMIUM_DECIMALS = 4;

export type Result<T> = { ok: true; value: T } | { ok: false; reason: string };

const fail = (reason: string): { ok: false; reason: string } => ({ ok: false, reason });

/** Importes en los motivos de rechazo: es-ES con 2 decimales («2.000,00»).
 *  Local a propósito: este módulo no importa nada fuera de ./types (los
 *  golden lo cargan con node --experimental-strip-types, sin alias @/). */
const importeEs = (n: number): string =>
    new Intl.NumberFormat('es-ES', { useGrouping: 'always', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

/** Fecha civil (yyyy-mm-dd) de un instante en Nueva York (zona de los vencimientos OCC). */
export function newYorkDate(epochMs: number): string {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'America/New_York',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(new Date(epochMs));
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
    return `${get('year')}-${get('month')}-${get('day')}`;
}

/** Fecha civil real con forma yyyy-mm-dd (rechaza 2026-13-45 y similares). */
export function isRealDate(iso: string): boolean {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return false;
    const [y, m, d] = iso.split('-').map(Number);
    const date = new Date(Date.UTC(y, m - 1, d));
    return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

function daysBetween(fromIso: string, toIso: string): number {
    const a = Date.parse(`${fromIso}T00:00:00Z`);
    const b = Date.parse(`${toIso}T00:00:00Z`);
    return Math.round((b - a) / 86_400_000);
}

function decimals(n: number): number {
    const s = String(n);
    if (s.includes('e')) return Infinity;
    const i = s.indexOf('.');
    return i === -1 ? 0 : s.length - i - 1;
}

/** Valida la identidad del contrato (sin mirar fechas relativas a hoy). */
export function validateOptionContract(contract: OptionContract): Result<OptionContract> {
    if (!contract || typeof contract !== 'object') return fail('Contrato de opción ausente.');
    if (!/^[A-Za-z][A-Za-z0-9.\-]{0,9}$/.test(String(contract.underlying ?? '').trim())) {
        return fail('Subyacente inválido.');
    }
    if (contract.callPut !== 'call' && contract.callPut !== 'put') return fail('Tipo debe ser call o put.');
    if (!Number.isFinite(contract.strike) || contract.strike <= 0) return fail('Strike debe ser un número mayor que 0.');
    if (!isRealDate(String(contract.expiry))) return fail('Vencimiento inválido (se espera yyyy-mm-dd real).');
    if (contract.deliverable !== 'acciones') return fail('Solo se admite entrega de acciones en fase 1.');
    if (contract.adjusted) {
        return fail(
            'Contrato ajustado por una operacion corporativa: no soportado en fase 1 (el deliverable y el multiplicador cambian y no se modelan).',
        );
    }
    if (contract.multiplier !== STANDARD_MULTIPLIER) {
        return fail('Solo se admiten contratos estándar con multiplicador 100.');
    }
    return { ok: true, value: contract };
}

export type ExpiryBadge = 'vigente' | 'vence-hoy' | 'vencida';

/**
 * Estado del vencimiento para MOSTRAR una posición de opción, calculado con
 * la fecha civil del contrato en Nueva York (zona de los vencimientos OCC),
 * no con la tz del usuario. El día del vencimiento es 'vence-hoy'.
 */
export function expiryBadge(expiryIso: string, nowMs: number): ExpiryBadge {
    const days = daysBetween(newYorkDate(nowMs), expiryIso);
    return days < 0 ? 'vencida' : days === 0 ? 'vence-hoy' : 'vigente';
}

export type ExpirationState = {
    /** 'vigente' hasta el dia de vencimiento incluido (hora de Nueva York). */
    status: 'vigente' | 'vencido';
    /** Dias hasta el vencimiento (0 = vence hoy); negativo si ya vencio. */
    daysToExpiry: number;
};

export function expirationState(contract: OptionContract, nowMs: number): ExpirationState {
    const today = newYorkDate(nowMs);
    const days = daysBetween(today, contract.expiry);
    return { status: days >= 0 ? 'vigente' : 'vencido', daysToExpiry: days };
}

/** Prima total en la divisa del fill: prima por accion x 100 x contratos (sin fee). */
export function premiumTotal(pricePerShare: number, contracts: number, multiplier = STANDARD_MULTIPLIER): number {
    return (Math.round(pricePerShare * 10 ** MAX_PREMIUM_DECIMALS) * contracts * multiplier) / 10 ** MAX_PREMIUM_DECIMALS;
}

/**
 * Efecto en cash de un fill de opcion: compra = -(prima + fee); venta =
 * +(prima - fee). Redondeado a centimos.
 */
export function optionCashDelta(fill: Pick<Fill, 'side' | 'price' | 'quantity' | 'fee' | 'instrument'>): number {
    const multiplier = fill.instrument.kind === 'opcion' ? fill.instrument.contract.multiplier : STANDARD_MULTIPLIER;
    const premium = premiumTotal(fill.price, fill.quantity, multiplier);
    const cents = Math.round((fill.side === 'buy' ? -(premium + fill.fee) : premium - fill.fee) * 100);
    return cents / 100;
}

export type OptionOrderInput = {
    contract: OptionContract;
    side: 'buy' | 'sell';
    openClose: 'open' | 'close';
    contracts: number;
    /** Prima por accion introducida por el usuario. */
    premium: number;
    currency: Currency;
    fee: number;
    executedAt: number;
    clientOrderId: string;
    /** Contratos vivos de ESTE contrato en la cuenta (para validar cierres). */
    heldContracts: number;
    /** Saldo disponible en la divisa del fill (para validar aperturas). */
    availableCash: number;
};

/**
 * Valida una orden de opcion manual y devuelve el Fill listo para el libro,
 * o el motivo del rechazo. No toca BD; el servidor debe repetir la
 * validacion con datos reales antes de grabar.
 */
export function buildOptionFill(input: OptionOrderInput): Result<Fill> {
    const contractCheck = validateOptionContract(input.contract);
    if (!contractCheck.ok) return contractCheck;

    const buyOpen = input.side === 'buy' && input.openClose === 'open';
    const sellClose = input.side === 'sell' && input.openClose === 'close';
    if (!buyOpen && !sellClose) {
        return fail('Fase 1 solo admite comprar para abrir y vender para cerrar (sin vender para abrir ni cortos).');
    }
    if (!Number.isInteger(input.contracts) || input.contracts <= 0) return fail('Los contratos deben ser un entero mayor que 0.');
    if (!Number.isFinite(input.premium) || input.premium <= 0) return fail('La prima debe ser mayor que 0.');
    if (decimals(input.premium) > MAX_PREMIUM_DECIMALS) return fail(`La prima admite como máximo ${MAX_PREMIUM_DECIMALS} decimales.`);
    if (input.currency !== 'EUR' && input.currency !== 'USD') return fail('Divisa no soportada.');
    if (!Number.isFinite(input.fee) || input.fee < 0) return fail('La comisión no puede ser negativa.');
    if (!Number.isFinite(input.executedAt) || input.executedAt <= 0) return fail('Fecha de ejecución inválida.');
    if (!input.clientOrderId) return fail('Falta clientOrderId.');
    if (expirationState(input.contract, input.executedAt).status === 'vencido') {
        return fail('El contrato ya venció en la fecha de ejecución indicada.');
    }

    if (sellClose && input.contracts > input.heldContracts) {
        return fail(`No se pueden cerrar ${input.contracts} contratos: solo hay ${input.heldContracts} abiertos.`);
    }
    if (sellClose) {
        // Sin sobregiro: la comision del cierre tambien debe caber en el cash
        // que queda tras abonar la prima (la apertura ya lo chequea).
        const proceeds = premiumTotal(input.premium, input.contracts, input.contract.multiplier);
        if (!Number.isFinite(input.availableCash) || input.fee > input.availableCash + proceeds + 1e-9) {
            const disponible = Number.isFinite(input.availableCash) ? importeEs(input.availableCash + proceeds) : 'N/D';
            return fail(`La comisión (${importeEs(input.fee)}) supera el efectivo disponible tras el cierre (${disponible}): la demo no admite sobregiro.`);
        }
    }
    if (buyOpen) {
        const cost = -optionCashDelta({
            side: 'buy',
            price: input.premium,
            quantity: input.contracts,
            fee: input.fee,
            instrument: { kind: 'opcion', contract: input.contract, name: '' },
        });
        if (!Number.isFinite(input.availableCash) || cost > input.availableCash + 1e-9) {
            return fail(`Saldo ${input.currency} insuficiente: la compra cuesta ${importeEs(cost)} y hay ${Number.isFinite(input.availableCash) ? importeEs(input.availableCash) : 'N/D'}.`);
        }
    }

    const name = `${input.contract.underlying.toUpperCase()} ${input.contract.expiry} ${input.contract.strike} ${input.contract.callPut === 'call' ? 'Call' : 'Put'}`;
    return {
        ok: true,
        value: {
            instrument: { kind: 'opcion', contract: input.contract, name },
            side: input.side,
            openClose: input.openClose,
            quantity: input.contracts,
            price: input.premium,
            currency: input.currency,
            fee: input.fee,
            executedAt: input.executedAt,
            source: 'manual-simulado',
            clientOrderId: input.clientOrderId,
        },
    };
}

/** Valor intrinseco por accion (>= 0) con el precio del subyacente dado. */
export function intrinsicValue(contract: OptionContract, underlyingPrice: number): number {
    const raw = contract.callPut === 'call' ? underlyingPrice - contract.strike : contract.strike - underlyingPrice;
    return Math.max(0, raw);
}

export type ExpiryOutcome =
    | { status: 'vigente' }
    | { status: 'sin-valor'; intrinsicPerShare: 0 }
    | { status: 'pendiente-liquidacion'; intrinsicPerShare: number | null; reason: string };

/**
 * Resultado al vencer. `underlyingClose` es el cierre del subyacente el
 * dia del vencimiento si hay fuente fechada; null si no hay dato.
 * - Sin dato: pendiente (NO se asume OTM ni ITM).
 * - Intrinseco 0: sin valor (se podra cerrar a 0 con PyG realizado).
 * - Intrinseco > 0: pendiente; el ejercicio/asignacion no se modela en fase 1.
 */
export function expiryOutcome(contract: OptionContract, nowMs: number, underlyingClose: number | null): ExpiryOutcome {
    if (expirationState(contract, nowMs).status === 'vigente') return { status: 'vigente' };
    if (underlyingClose === null || !Number.isFinite(underlyingClose) || underlyingClose <= 0) {
        return {
            status: 'pendiente-liquidacion',
            intrinsicPerShare: null,
            reason: 'Sin cierre fechado del subyacente: no se asume si venció dentro o fuera del dinero.',
        };
    }
    const intrinsic = intrinsicValue(contract, underlyingClose);
    if (intrinsic === 0) return { status: 'sin-valor', intrinsicPerShare: 0 };
    return {
        status: 'pendiente-liquidacion',
        intrinsicPerShare: intrinsic,
        reason: 'Dentro del dinero al vencer: ejercicio/asignación no modelados en fase 1; registra el cierre manualmente.',
    };
}
