/**
 * Adaptador persistencia -> libro (P1 del auditor): un documento corrupto
 * NUNCA se omite en silencio. Cada documento o se convierte en una entrada
 * del libro o produce una violation visible con su id.
 */

// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension
// .ts en runtime; tsc la prohibe (TS5097). Mismo patron que los guards.
import { toFill, type Fill, type LedgerEntry } from './types.ts';

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

/** Orden total persistido: (executedAt, createdAt, _id). NUNCA depende del
 * orden en que lleguen los docs (índice de array): todas las lecturas del
 * libro recalculan en el mismo orden. */
export function persistedOrder(a: PersistedTradeDoc, b: PersistedTradeDoc): number {
    const ta = a.executedAt instanceof Date ? a.executedAt.getTime() : 0;
    const tb = b.executedAt instanceof Date ? b.executedAt.getTime() : 0;
    if (ta !== tb) return ta - tb;
    const ca = a.createdAt instanceof Date ? a.createdAt.getTime() : 0;
    const cb = b.createdAt instanceof Date ? b.createdAt.getTime() : 0;
    if (ca !== cb) return ca - cb;
    return String(a._id ?? '').localeCompare(String(b._id ?? ''));
}

/** Documentos persistidos -> entradas del libro; lo corrupto queda en violations. */
export function docsToLedger(docs: PersistedTradeDoc[]): AdaptedLedger {
    const entries: LedgerEntry[] = [];
    const violations: string[] = [];
    for (const doc of docs.slice().sort(persistedOrder)) {
        // Los rechazos no son movimientos del libro: viven en el historial,
        // no en la contabilidad. Un rechazo CON precio es corrupción y se avisa.
        if (doc.status === 'rejected') {
            if (doc.fillPrice != null) violations.push(`doc ${docId(doc)}: rejected con fillPrice (corrupción), ignorado del libro`);
            continue;
        }
        const executedAtMs = doc.executedAt instanceof Date ? doc.executedAt.getTime() : NaN;
        const tiebreak = doc.createdAt instanceof Date ? doc.createdAt.getTime() : undefined;
        if (doc.kind === 'fx') {
            if (!Number.isFinite(executedAtMs) || executedAtMs <= 0) {
                violations.push(`doc ${docId(doc)}: fx sin executedAt válido; no entra en el libro`);
                continue;
            }
            if (!doc.fxFrom || !doc.fxTo || doc.fxFrom === doc.fxTo || !(doc.fillPrice != null && doc.fillPrice > 0) || !(doc.quantity > 0)) {
                violations.push(`doc ${docId(doc)}: fx inválida (from/to/tipo/importe); no entra en el libro`);
                continue;
            }
            entries.push({
                kind: 'fx', from: doc.fxFrom, to: doc.fxTo, amountFrom: doc.quantity, rate: doc.fillPrice,
                executedAt: executedAtMs, source: 'manual-simulado', clientOrderId: doc.clientOrderId, tiebreak,
            });
            continue;
        }
        if (doc.kind === 'opcion' && (!doc.contract || typeof doc.contract !== 'object')) {
            violations.push(`doc ${docId(doc)}: opción sin contrato (corrupción); no entra en el libro`);
            continue;
        }
        if (!Number.isFinite(executedAtMs)) {
            violations.push(`doc ${docId(doc)}: fill sin executedAt válido; no entra en el libro`);
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
