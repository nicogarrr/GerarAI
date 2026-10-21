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
 * Número tecleado por un usuario español: admite coma decimal y punto de
 * miles ("42,5", "1.234,56", "98.5"). No es contabilidad: solo parseo de
 * formulario; la validación real está en el servidor.
 */
export function parseEsNumber(raw: string): number {
    const cleaned = raw.trim().replace(/\s/g, '');
    if (cleaned === '') return Number.NaN;
    if (cleaned.includes(',')) {
        // con coma: los puntos son miles ("1.234,56")
        return Number(cleaned.replace(/\./g, '').replace(',', '.'));
    }
    if (/^-?\d{1,3}(\.\d{3})+$/.test(cleaned)) {
        // sin coma, punto(s) cada 3 dígitos: miles ("1.234", "1.234.567")
        return Number(cleaned.replace(/\./g, ''));
    }
    // punto decimal simple ("98.5") o entero; cualquier otra cosa es NaN
    // (Number no hace parseo parcial: "42abc" no cuela).
    return Number(cleaned);
}

export type SubmitFill = (input: FillSubmit) => Promise<SubmitResult>;
export type SubmitFx = (input: FxSubmit) => Promise<SubmitResult>;
