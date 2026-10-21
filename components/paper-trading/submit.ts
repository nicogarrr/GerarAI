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
    amountFrom: number;
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

export type SubmitFill = (input: FillSubmit) => Promise<SubmitResult>;
export type SubmitFx = (input: FxSubmit) => Promise<SubmitResult>;
