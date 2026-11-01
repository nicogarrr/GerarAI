/**
 * Transporte UI -> server action de la cuenta demo manual.
 * Espejo de los tipos de lib/actions/manual-demo.actions.ts (payloads de
 * formulario y vistas), no tipos de dominio: el dominio vive en
 * lib/paper-trading/types.ts (contrato) y nadie lo duplica aqui.
 */
import type { Currency, Instrument } from '@/lib/paper-trading/types';

/** Una orden de compra/venta ya ejecutada, con el precio que introduce el usuario. */
export type FillSubmit = {
    instrument: Instrument;
    side: 'buy' | 'sell';
    openClose: 'open' | 'close';
    quantity: number;
    price: number;
    currency: Currency;
    /** Comision de la operacion (>= 0; 0 por defecto en la demo). */
    fee: number;
    /** Cuando se ejecuto, epoch UTC en milisegundos; no futura. */
    executedAt: number;
    /** Idempotencia: lo genera el cliente por intento; un reenvio reusa el mismo. */
    clientOrderId: string;
};

/** Conversion EUR<->USD simulada con el tipo que introduce el usuario. */
export type FxSubmit = {
    from: Currency;
    to: Currency;
    amount: number;
    rate: number;
    /** Cuando se ejecuto, epoch UTC en milisegundos; no futura. */
    executedAt: number;
    clientOrderId: string;
};

/** Resultado explicito: filled / rejected (con reason) / duplicate, o fallo de la accion. */
export type SubmitOutcome = 'filled' | 'rejected' | 'duplicate';
export type SubmitResult =
    | { ok: true; outcome: SubmitOutcome; reason: string | null; state: DemoStateView }
    | { ok: false; error: string };

/**
 * Politica de idempotencia del clientOrderId tras cada resultado:
 * - filled / rejected / duplicate-con-reason (duplicado de un RECHAZO
 *   persistido): estados terminales confirmados por el servidor -> id nuevo,
 *   asi corregir y reenviar registra una operacion nueva.
 * - duplicate-sin-reason (duplicado de un FILL persistido): mismo id; un
 *   reintento (doble click, red) no genera otra orden.
 * - !ok (fallo de red o desconocido): mismo id SIEMPRE; pudo haber fill
 *   persistido y regenerar crearia dobles ordenes. Reintento idempotente
 *   con el mismo id hasta reconciliar.
 */
export function clientOrderIdAfter(result: SubmitResult, current: string, gen: () => string): string {
    if (!result.ok) return current;
    if (result.outcome === 'duplicate' && result.reason === null) return current;
    return gen();
}

/** Vista de la cuenta tal cual la devuelve la accion (espejo de ManualDemoStateView). */
export type DemoStateView = {
    cashEUR: number;
    cashUSD: number;
    realizedEUR: number;
    realizedUSD: number;
    positions: DemoPositionView[];
    /** Incidencias de integridad detectadas al recalcular; NUNCA se ocultan. */
    violations: string[];
    notices: string[];
};

export type DemoPositionView = {
    instrumentKey: string;
    name: string;
    kind: 'accion' | 'opcion';
    currency: Currency;
    quantity: number;
    avgCost: number;
    realizedPnl: number;
    /** Solo opciones: fecha del contrato y estado de vencimiento (servidor, zona NY/OCC). */
    optionExpiry: string | null;
    optionBadge: 'vigente' | 'vence-hoy' | 'vencida' | null;
};

/**
 * Fila del historial tal cual la devuelve la accion (espejo de
 * ManualDemoOrderRow): incluye las RECHAZADAS, que nunca se muestran como
 * fills (fillPrice null y badge propio).
 */
export type HistoryRow = {
    clientOrderId: string;
    kind: 'accion' | 'opcion' | 'fx';
    symbol: string;
    name: string;
    side: 'buy' | 'sell';
    openClose: 'open' | 'close';
    quantity: number;
    status: 'filled' | 'rejected';
    fillPrice: number | null;
    currency: Currency;
    fee: number;
    /** Null cuando la orden fue rechazada. */
    executedAt: number | null;
    rejectReason: string | null;
    createdAt: number;
    simulated: true;
};

/**
 * Página del historial paginado (espejo de ManualDemoHistoryPage de
 * lib/actions/manual-demo.actions.ts): cursor estable
 * (createdAt, _id) sin offset — las filas nuevas entran por arriba y no
 * desplazan el recorrido entre páginas.
 */
export type HistoryPageResult =
    | { ok: true; orders: HistoryRow[]; hasMore: boolean; nextBefore: string | null }
    | { ok: false; message: string };

/**
 * Entrada numérica SIN ambigüedad: un único separador (coma o punto) que
 * siempre es decimal; NO se aceptan separadores de miles. "1.234" es 1.234,
 * nunca 1234. Cadenas con dos tipos de separador o separadores repetidos
 * ("1.234,56", "1,2,3", "1.234.567") son ambiguas y se rechazan (NaN) para
 * pedir formato claro. El formateo es-ES con miles es solo de salida.
 */
// i18n: la pista vive en messages/<locale>/paperTrading.json (numInputHint).
// Este literal es queda por compatibilidad con importadores node directos
// (guards); scripts/manual-demo-ui.guard.test.ts verifica que coincide con
// el diccionario.
export const NUM_INPUT_HINT = 'decimales con coma o punto, sin separador de miles (1234,56)';

export function parseEsNumber(raw: string): number {
    // Se recortan espacios solo en los extremos (pegar desde otra app).
    // Cualquier espacio INTERNO invalida: no se fusionan dígitos a ciegas
    // ("1 2" NO es 12, "1 234,5" es un miles encubierto y se rechaza).
    const cleaned = raw.trim();
    if (!/^-?\d+([.,]\d+)?$/.test(cleaned)) return Number.NaN;
    return Number(cleaned.replace(',', '.'));
}

export type SubmitFill = (input: FillSubmit) => Promise<SubmitResult>;
export type SubmitFx = (input: FxSubmit) => Promise<SubmitResult>;
