/**
 * Adaptador persistencia -> libro (P1 del auditor): un documento corrupto
 * NUNCA se omite en silencio. Cada documento o se convierte en una entrada
 * del libro o produce una violation visible con su id.
 */

// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension
// .ts en runtime; tsc la prohibe (TS5097). Mismo patron que los guards.
import { toFill, type Fill, type FxConversion, type LedgerEntry } from './types.ts';

export type PersistedTradeDoc = {
    _id?: unknown;
    kind: 'accion' | 'opcion' | 'fx';
    symbol?: string;
    name?: string;
    contract?: {
        underlying: string;
        callPut: 'call' | 'put';
        strike: number;
        expiry: string;
        multiplier: number;
        deliverable: 'acciones';
        adjusted: boolean;
    } | null;
    fxFrom?: 'EUR' | 'USD' | null;
    fxTo?: 'EUR' | 'USD' | null;
    side?: 'buy' | 'sell';
    openClose?: 'open' | 'close';
    quantity: number;
    status: 'filled' | 'rejected';
    fillPrice: number | null;
    currency?: 'EUR' | 'USD' | null;
    fee: number;
    executedAt: Date | null;
    clientOrderId: string;
    createdAt?: Date;
};

export type AdaptedLedger = { entries: LedgerEntry[]; violations: string[] };

const docId = (doc: PersistedTradeDoc) => String(doc._id ?? doc.clientOrderId ?? 'desconocido');

/** Documentos persistidos -> entradas del libro; lo corrupto queda en violations. */
export function docsToLedger(docs: PersistedTradeDoc[]): AdaptedLedger {
    const entries: LedgerEntry[] = [];
    const violations: string[] = [];
    for (const doc of docs) {
        // Los rechazos no son movimientos del libro: viven en el historial,
        // no en la contabilidad. Un rechazo CON precio es corrupción y se avisa.
        if (doc.status === 'rejected') {
            if (doc.fillPrice != null) violations.push(`doc ${docId(doc)}: rejected con fillPrice (corrupción), ignorado del libro`);
            continue;
        }
        const executedAtMs = doc.executedAt instanceof Date ? doc.executedAt.getTime() : NaN;
        const tiebreak = doc.createdAt instanceof Date ? doc.createdAt.getTime() : undefined;
        if (doc.kind === 'fx') {
            if (!doc.fxFrom || !doc.fxTo || doc.fxFrom === doc.fxTo || !(doc.fillPrice != null && doc.fillPrice > 0)) {
                violations.push(`doc ${docId(doc)}: fx inválida (from/to/tipo); no entra en el libro`);
                continue;
            }
            entries.push({
                kind: 'fx', from: doc.fxFrom, to: doc.fxTo, amountFrom: doc.quantity, rate: doc.fillPrice,
                executedAt: executedAtMs, source: 'manual-simulado', clientOrderId: doc.clientOrderId, tiebreak,
            });
            continue;
        }
        const instrument: Fill['instrument'] = doc.kind === 'opcion'
            ? { kind: 'opcion', contract: doc.contract!, name: doc.name ?? `${doc.contract?.underlying ?? '?'} opción` }
            : { kind: 'accion', symbol: doc.symbol ?? '?', name: doc.name ?? doc.symbol ?? '?' };
        const fill = toFill({
            instrument,
            side: doc.side === 'sell' ? 'sell' : 'buy',
            openClose: doc.openClose === 'close' ? 'close' : 'open',
            quantity: doc.quantity,
            price: doc.fillPrice ?? NaN,
            currency: doc.currency ?? 'EUR',
            fee: doc.fee ?? 0,
            executedAt: executedAtMs,
            clientOrderId: doc.clientOrderId ?? '',
        });
        if (!fill) {
            violations.push(`doc ${docId(doc)}: fill corrupto (precio/cantidad/fecha); no entra en el libro`);
            continue;
        }
        entries.push({ ...fill, tiebreak });
    }
    return { entries, violations };
}
