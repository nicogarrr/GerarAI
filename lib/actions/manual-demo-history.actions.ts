'use server';

/**
 * Historial PAGINADO de la cuenta demo manual (read-model visual del panel).
 *
 * Módulo aparte de manual-demo.actions.ts a propósito (coordinación entre
 * agentes 22-oct-2026): aquel archivo tiene otro mantenedor concurrente y
 * esta consulta es aditiva — mismo filtro (userId SOLO de sesión) y mismo
 * orden (createdAt desc, _id desc) que getManualDemoOrders, pero con cursor
 * estable y límite. Cuando aquel archivo quede libre se consolida.
 *
 * - Cursor compuesto (createdAt, _id) del ÚLTIMO row de la página anterior:
 *   keyset pagination, sin offset — las filas nuevas llegan por arriba
 *   (createdAt mayor) y nunca desplazan el recorrido, así que no se pierden
 *   ni se repiten filas entre páginas ni aunque haya inserciones concurrentes.
 * - Autorización en TODA página: el userId sale solo de la sesión y va en
 *   cada query; un cursor de otra cuenta no filtra datos ajenos (manda el
 *   filtro userId) y un cursor con formato inválido se rechaza.
 * - Contabilidad intacta: lectura pura del historial; el libro y el estado
 *   derivado (readLedger) no pasan por aquí.
 */

import { Types, type QueryFilter } from 'mongoose';
import { connectToDatabase } from '@/database/mongoose';
import { ManualDemoTrade, type ManualDemoTradeDoc } from '@/database/models/manual-demo.model';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import type { ManualDemoFailure, ManualDemoOrderRow } from '@/lib/actions/manual-demo.actions';

/** Página por defecto: una pantalla larga de historial. */
const HISTORY_DEFAULT_LIMIT = 200;
/** Tope duro por página: nunca un volcado ilimitado de la colección. */
const HISTORY_MAX_LIMIT = 500;
/** `ms:id` — estricto: un cursor manipulado se rechaza, no se reinterpreta. */
const CURSOR_RE = /^(\d{1,15}):([A-Za-z0-9_-]{1,64})$/;
const OBJECTID_RE = /^[a-f0-9]{24}$/i;

export type ManualDemoHistoryPage =
    | { ok: true; orders: ManualDemoOrderRow[]; hasMore: boolean; nextBefore: string | null }
    | ManualDemoFailure;

/** Espejo de toRow de manual-demo.actions (local allí); consolidar al unificar módulos. */
function toRow(doc: ManualDemoTradeDoc): ManualDemoOrderRow {
    return {
        clientOrderId: doc.clientOrderId,
        kind: doc.kind,
        symbol: doc.symbol,
        name: doc.name,
        side: doc.side,
        openClose: doc.openClose,
        quantity: doc.quantity,
        status: doc.status,
        fillPrice: doc.fillPrice,
        currency: doc.currency,
        fee: doc.fee,
        executedAt: doc.executedAt instanceof Date ? doc.executedAt.getTime() : null,
        rejectReason: doc.rejectReason,
        createdAt: doc.createdAt instanceof Date ? doc.createdAt.getTime() : 0,
        simulated: true,
    };
}

function parseBefore(raw: unknown): { createdAtMs: number; id: string } | null | 'invalid' {
    if (raw === undefined || raw === null) return null;
    if (typeof raw !== 'string') return 'invalid';
    const m = CURSOR_RE.exec(raw);
    if (!m) return 'invalid';
    const createdAtMs = Number(m[1]);
    if (!Number.isSafeInteger(createdAtMs) || createdAtMs <= 0) return 'invalid';
    return { createdAtMs, id: m[2] };
}

function parseLimit(raw: unknown): number {
    if (raw === undefined || raw === null) return HISTORY_DEFAULT_LIMIT;
    const n = typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : raw;
    if (typeof n !== 'number' || !Number.isFinite(n)) return HISTORY_DEFAULT_LIMIT;
    return Math.min(HISTORY_MAX_LIMIT, Math.max(1, Math.floor(n)));
}

export async function getManualDemoHistory(raw?: unknown): Promise<ManualDemoHistoryPage> {
    let userId: string;
    try {
        userId = (await requireAuthenticatedUser()).id;
    } catch (error) {
        if (error instanceof Error && error.name === 'AuthenticationError') {
            return { ok: false, message: 'Inicia sesión para usar la cuenta demo.' };
        }
        throw error;
    }
    const input = (raw !== null && typeof raw === 'object' ? raw : {}) as { before?: unknown; limit?: unknown };
    const cursor = parseBefore(input.before);
    if (cursor === 'invalid') return { ok: false, message: 'Cursor de historial inválido.', field: 'before' };
    const limit = parseLimit(input.limit);
    try {
        await connectToDatabase();
        const filter: QueryFilter<ManualDemoTradeDoc> = { userId };
        if (cursor) {
            const boundary = new Date(cursor.createdAtMs);
            // Los _id reales son ObjectId: hay que reconstruir el tipo o la
            // comparación de desempate se evalúa por orden de tipos BSON
            // (ObjectId > string) y el desempate no filtraría nada.
            const boundaryId = OBJECTID_RE.test(cursor.id) ? new Types.ObjectId(cursor.id) : cursor.id;
            filter.$or = [
                { createdAt: { $lt: boundary } },
                { createdAt: boundary, _id: { $lt: boundaryId } },
            ];
        }
        const docs = (await ManualDemoTrade.find(filter)
            .sort({ createdAt: -1, _id: -1 })
            .limit(limit + 1)) as unknown as ManualDemoTradeDoc[];
        const hasMore = docs.length > limit;
        const pageDocs = hasMore ? docs.slice(0, limit) : docs;
        const last = pageDocs[pageDocs.length - 1];
        const nextBefore = hasMore && last ? `${last.createdAt.getTime()}:${String(last._id)}` : null;
        return { ok: true, orders: pageDocs.map(toRow), hasMore, nextBefore };
    } catch (error) {
        console.error('getManualDemoHistory:', error);
        return { ok: false, message: 'No se pudo completar la operación. Inténtalo de nuevo en unos minutos.' };
    }
}
