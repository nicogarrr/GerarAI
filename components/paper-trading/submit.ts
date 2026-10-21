/**
 * Transporte UI -> server action de la cuenta demo manual.
 * Son payloads de formulario, no tipos de dominio: el dominio vive en
 * lib/paper-trading/types.ts (contrato) y nadie lo duplica aqui.
 */
import type { Currency, Instrument } from '@/lib/paper-trading/types';

export type SubmitResult = { ok: true } | { ok: false; error: string };

/** Una orden de compra/venta ya ejecutada, con el precio que introduce el usuario. */
export type FillSubmit = {
    instrument: Instrument;
    side: 'buy' | 'sell';
    openClose: 'open' | 'close';
    quantity: number;
    price: number;
    currency: Currency;
    /** Idempotencia: lo genera el cliente por intento; un reenvio reusa el mismo. */
    clientOrderId: string;
};

/** Conversion EUR<->USD simulada con el tipo que introduce el usuario. */
export type FxSubmit = {
    from: Currency;
    to: Currency;
    amountFrom: number;
    rate: number;
    clientOrderId: string;
};

export type SubmitFill = (input: FillSubmit) => Promise<SubmitResult>;
export type SubmitFx = (input: FxSubmit) => Promise<SubmitResult>;
