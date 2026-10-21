/**
 * CONTRATO de la cuenta demo manual (paper trading tipo IBKR demo).
 * Frontera compartida entre contabilidad, actions, UI y opciones: todo
 * módulo del paper manual consume estos tipos y NADIE define los suyos.
 *
 * Decisiones fijadas (cambiarlas exige tocar este fichero y avisar):
 * - Es una DEMO MANUAL, separada del sistema de propuestas/calibración
 *   LLM existente (proPicks, data-engine Postgres). Colecciones y rutas
 *   propias; la UI lo etiqueta visiblemente.
 * - Cash MULTIDIVISA: la cuenta nace con 100.000 EUR ficticios; una venta
 *   en USD abona saldo USD. Nunca se resta USD de un saldo EUR. La
 *   conversión entre divisas es una operación manual simulada (FxConversion)
 *   con el tipo de cambio introducido por el usuario, etiquetada como tal.
 * - Comisiones: fee por fill, en la divisa del fill. Fase 1: fee=0 como
 *   SIMPLIFICACIÓN documentada (no es una promesa de gratuidad real).
 * - Idempotencia: toda orden lleva clientOrderId; el índice único
 *   (userId, clientOrderId) está en database/models/manual-demo.model.ts.
 * - Modo de fills: SOLO 'manual-simulado' (precio introducido por el
 *   usuario, etiquetado). No es una ejecución de mercado ni un motor de
 *   órdenes: no hay estados pending/working que "se ejecuten". Un fill
 *   manual NO es equivalente a una ejecución real.
 */

export type Currency = 'EUR' | 'USD';

/** Identidad completa de un contrato de opción (sin ambigüedad). */
export interface OptionContract {
    underlying: string;
    callPut: 'call' | 'put';
    strike: number;
    /** Fecha de vencimiento ISO (yyyy-mm-dd). */
    expiry: string;
    /** Multiplicador del contrato (100 SOLO en estándar; OCC). */
    multiplier: number;
    /** Entrega: acciones del subyacente (fase 1, única soportada). */
    deliverable: 'acciones';
    /** Contratos ajustados por corporativas: fase 1 se RECHAZAN con mensaje honesto. */
    adjusted: boolean;
}

export type Instrument =
    | { kind: 'accion'; symbol: string; name: string }
    | { kind: 'opcion'; contract: OptionContract; name: string };

/**
 * Un fill ES una operación ejecutada: solo se construye con precio>0,
 * cantidad entera>0 y moneda. Las órdenes rechazadas NUNCA entran en la
 * contabilidad (van al historial como rechazadas, no al libro).
 */
export interface Fill {
    instrument: Instrument;
    side: 'buy' | 'sell';
    /** Apertura o cierre de posición (opciones; en acciones open=buy/close=sell). */
    openClose: 'open' | 'close';
    quantity: number;
    /** Precio por acción / prima por acción de la opción (sin multiplicador). */
    price: number;
    currency: Currency;
    fee: number;
    /** Cuándo se ejecutó de verdad, en MILISEGUNDOS epoch UTC (Date.getTime()).
     *  El FIFO ordena por esto, no por createdAt del documento. */
    executedAt: number;
    source: 'manual-simulado';
    clientOrderId: string;
    /**
     * Desempate ESTABLE para fills con el mismo executedAt: el servidor lo
     * rellena con el createdAt (ms) de la fila persistida. Nunca se usa el
     * orden del array para desempatar (N-auditoría).
     */
    tiebreak?: number;
}

/** Conversión manual simulada entre saldos (EUR<->USD). from != to SIEMPRE:
 * convertir una divisa en sí misma crearía dinero (N1 del auditor). */
export interface FxConversion {
    kind: 'fx';
    from: Currency;
    to: Currency;
    amountFrom: number;
    /** Unidades de `to` por 1 de `from`, introducido por el usuario (simulado). */
    rate: number;
    /** MILISEGUNDOS epoch UTC (Date.getTime()). */
    executedAt: number;
    source: 'manual-simulado';
    clientOrderId: string;
    /**
     * Desempate ESTABLE para fills con el mismo executedAt: el servidor lo
     * rellena con el createdAt (ms) de la fila persistida. Nunca se usa el
     * orden del array para desempatar (N-auditoría).
     */
    tiebreak?: number;
}

export type LedgerEntry = Fill | FxConversion;

export interface PaperPosition {
    instrumentKey: string;
    name: string;
    kind: 'accion' | 'opcion';
    currency: Currency;
    quantity: number;
    /** Coste medio FIFO por unidad (acción / prima por acción). */
    avgCost: number;
    realizedPnl: number;
}

export interface AccountState {
    /** Saldo por divisa. */
    cashByCurrency: Record<Currency, number>;
    realizedPnlByCurrency: Record<Currency, number>;
    positions: PaperPosition[];
    /**
     * Incidencias de integridad detectadas al recalcular (sobreventa,
     * sobregiro, fill inválido). NUNCA se ocultan: el servidor valida antes
     * de grabar Y la contabilidad defiende; si algo se coló, aquí se ve.
     */
    violations: string[];
}

/** Clave estable de instrumento para el libro (opciones incluyen el contrato). */
export function instrumentKey(instrument: Instrument): string {
    if (instrument.kind === 'accion') return `A:${instrument.symbol.toUpperCase()}`;
    const c = instrument.contract;
    return `O:${c.underlying.toUpperCase()}:${c.expiry}:${c.callPut}:${c.strike}:${c.multiplier}`;
}

/** Datos de contrato recuperados de una instrumentKey de opción; null si no es opción válida fase 1. */
export function parseOptionKey(key: string): { underlying: string; expiry: string; callPut: 'call' | 'put'; strike: number; multiplier: number } | null {
    if (!key.startsWith('O:')) return null;
    const parts = key.split(':');
    if (parts.length !== 6) return null;
    const [, underlying, expiry, callPut, strikeRaw, multiplierRaw] = parts;
    if (!underlying) return null;
    if (callPut !== 'call' && callPut !== 'put') return null;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(expiry)) return null;
    const strike = Number(strikeRaw);
    const multiplier = Number(multiplierRaw);
    if (!(strike > 0) || multiplier !== 100) return null;
    return { underlying, expiry, callPut, strike, multiplier };
}

/** Fills válidos o null (las órdenes inválidas no entran en el libro). */
export function toFill(input: Omit<Fill, 'source'> & { source?: Fill['source'] }): Fill | null {
    if (!Number.isFinite(input.price) || input.price <= 0) return null;
    if (!Number.isInteger(input.quantity) || input.quantity <= 0) return null;
    if (!Number.isFinite(input.fee) || input.fee < 0) return null;
    if (!Number.isFinite(input.executedAt) || input.executedAt <= 0) return null;
    if (!input.clientOrderId) return null;
    if (input.instrument.kind === 'opcion') {
        const c = input.instrument.contract;
        if (!c || typeof c !== 'object') return null; // runtime: contrato ausente (doc corrupto)
        if (c.adjusted) return null; // fase 1: contratos ajustados rechazados
        if (c.multiplier !== 100) return null; // fase 1: solo estándar
        if (!(c.strike > 0) || !/^\d{4}-\d{2}-\d{2}$/.test(c.expiry)) return null;
    }
    return { ...input, source: input.source ?? 'manual-simulado' };
}
