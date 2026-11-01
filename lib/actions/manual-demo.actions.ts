'use server';

/**
 * Acciones de servidor de la cuenta demo MANUAL de paper trading (tipo cuenta
 * paper de IBKR). Frontera compartida: lib/paper-trading/types.ts. Separada
 * del sistema de propuestas/calibración LLM (proPicks / research API):
 * colecciones propias y NUNCA pasa por researchRequest.
 *
 * Reglas de ESTE fichero (defensa en profundidad; modelo y contabilidad
 * tienen las suyas):
 * - Auth primero: requireAuthenticatedUser antes de leer o escribir nada; el
 *   userId sale SOLO de la sesión, nunca del cliente.
 * - Idempotencia: (userId, clientOrderId) único; un reintento devuelve el
 *   resultado ya grabado ('duplicate'), nunca duplica el fill.
 * - Concurrencia: libro + cuenta se actualizan en una transacción con
 *   escritura condicional { userId, version }; dos órdenes a la vez en la
 *   misma cuenta chocan y la perdedora reintenta (máx. 3). Si el despliegue
 *   no soporta transacciones, la acción lo dice y NO degrada a escrituras
 *   sin aislamiento.
 * - Validación cruzada aquí, no solo en el modelo: un fill siempre lleva
 *   precio y fecha; un rechazo nunca los lleva; fx siempre con from != to;
 *   opción siempre con contrato completo.
 * - Sin sobregiro ni sobreventa: se comprueba contra el estado derivado del
 *   libro DENTRO de la transacción y el rechazo es TOTAL (sin fills parciales).
 * - Sin feed automático: ningún fill sale de una cotización; todos son
 *   'manual-simulado' con el precio introducido por el usuario, y las
 *   respuestas lo etiquetan.
 */

import { connectToDatabase } from '@/database/mongoose';
import {
    MANUAL_DEMO_STARTING_CASH_EUR,
    ManualDemoAccount,
    ManualDemoTrade,
    type ManualDemoTradeDoc,
} from '@/database/models/manual-demo.model';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { formatNumber } from '@/lib/format';
import { sanitizeFinnhubQuote } from '@/lib/market/quote-freshness';
import { combineAbortSignals, createQuoteCache, type CachedQuote, type QuoteFetchAttempt } from '@/lib/market/quote-cache';
import { parseListingCurrencies, symbolFromKey, valuePositions, type DemoValuation, type ValuationQuote } from '@/lib/market/demo-valuation';
import { requestLocale } from '@/lib/research/backend-error-locale';
import { computeManualDemoAccount } from '@/lib/paper-trading/accounting';
import { docsToLedger } from '@/lib/paper-trading/ledger-adapter';
import { buildOptionFill, expiryBadge } from '@/lib/paper-trading/options';
import { parseOptionKey } from '@/lib/paper-trading/types';
import {
    instrumentKey,
    toFill,
    type AccountState,
    type Currency,
    type FxConversion,
    type Instrument,
    type LedgerEntry,
    type OptionContract,
} from '@/lib/paper-trading/types';
import type { ClientSession } from 'mongoose';

/** Etiquetas honestas que acompañan a TODA respuesta de la demo. */
const DEMO_NOTICES = [
    'Cuenta demo manual: el dinero es ficticio y no toca tu broker real.',
    'Cada ejecución es un fill manual simulado: introduces tú el precio; no se comprueba contra ninguna cotización en vivo y no equivale a una ejecución real.',
    'Comisiones: las órdenes registradas desde este formulario se anotan con comisión 0 simulada (simplificación de la demo, no la tarifa de ningún bróker); las comisiones históricas registradas se conservan tal cual y solo mueven el efectivo.',
    'El libro no aplica acciones corporativas (splits, dividendos): una posición mantenida a través de una queda descuadrada.',
];

const STARTING_CASH: Record<Currency, number> = { EUR: MANUAL_DEMO_STARTING_CASH_EUR, USD: 0 };

const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.\-]{0,19}$/;
const CLIENT_ORDER_RE = /^[A-Za-z0-9_-]{8,80}$/;
const MIN_EXECUTED_AT_MS = 1_000_000_000_000; // 2001-09-09 UTC: exige ms epoch, no segundos
const MAX_FUTURE_MS = 120_000;
const MAX_QUANTITY = 1_000_000;
const MAX_PRICE = 10_000_000;
const MAX_PRICE_DECIMALS = 4;
const MAX_RATE_DECIMALS = 6;
const MAX_TXN_ATTEMPTS = 3;

export type ManualDemoFailure = { ok: false; message: string; field?: string };

export type ManualDemoPositionView = {
    instrumentKey: string;
    name: string;
    kind: 'accion' | 'opcion';
    currency: Currency;
    quantity: number;
    avgCost: number;
    realizedPnl: number;
    /** Solo opciones: fecha civil del contrato (yyyy-mm-dd) y su estado de
     *  vencimiento calculado en el servidor con la zona del vencimiento
     *  (Nueva York, OCC). Informativo: el libro no ejerce ni expira solo. */
    optionExpiry: string | null;
    optionBadge: 'vigente' | 'vence-hoy' | 'vencida' | null;
};

export type ManualDemoStateView = {
    cashEUR: number;
    cashUSD: number;
    realizedEUR: number;
    realizedUSD: number;
    positions: ManualDemoPositionView[];
    /** Incidencias de integridad detectadas al recalcular; NUNCA se ocultan. */
    violations: string[];
    notices: string[];
};

export type ManualDemoAccountResult = { ok: true; state: ManualDemoStateView } | ManualDemoFailure;

export type ManualDemoOrderOutcome = 'filled' | 'rejected' | 'duplicate';

export type ManualDemoOrderResult =
    | { ok: true; outcome: ManualDemoOrderOutcome; reason: string | null; state: ManualDemoStateView }
    | ManualDemoFailure;

export type ManualDemoOrderRow = {
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
    executedAt: number | null;
    rejectReason: string | null;
    createdAt: number;
    simulated: true;
};

export type ManualDemoOrdersResult = { ok: true; orders: ManualDemoOrderRow[] } | ManualDemoFailure;

const failure = (message: string, field?: string): ManualDemoFailure =>
    field ? { ok: false, message, field } : { ok: false, message };

// Importes en motivos visibles: es-ES con 2 decimales y miles («2.000,00»),
// nunca Number.toFixed («2000.00») dentro de frases en español.
const money = (n: number): string => formatNumber(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** Mismo redondeo a céntimos que el libro (P3, accounting r2): el fast path
 * decide con la cifra EXACTA que aplicaría el replay, sin deriva de floats. */
const r2 = (n: number): number => Math.round(n * 100) / 100;

function toView(state: AccountState): ManualDemoStateView {
    return {
        cashEUR: state.cashByCurrency.EUR,
        cashUSD: state.cashByCurrency.USD,
        realizedEUR: state.realizedPnlByCurrency.EUR,
        realizedUSD: state.realizedPnlByCurrency.USD,
        positions: state.positions.map((p) => {
            const option = p.kind === 'opcion' ? parseOptionKey(p.instrumentKey) : null;
            return {
                instrumentKey: p.instrumentKey,
                name: p.name,
                kind: p.kind,
                currency: p.currency,
                quantity: p.quantity,
                avgCost: p.avgCost,
                realizedPnl: p.realizedPnl,
                optionExpiry: option?.expiry ?? null,
                optionBadge: option ? expiryBadge(option.expiry, Date.now()) : null,
            };
        }),
        violations: state.violations,
        notices: DEMO_NOTICES,
    };
}

async function requireDemoUser(): Promise<{ id: string } | ManualDemoFailure> {
    try {
        const user = await requireAuthenticatedUser();
        return { id: user.id };
    } catch (error) {
        if (error instanceof Error && error.name === 'AuthenticationError') {
            return failure('Inicia sesión para usar la cuenta demo.');
        }
        throw error;
    }
}

function isDemoUser(v: { id: string } | ManualDemoFailure): v is { id: string } {
    return 'id' in v;
}

/* ----------------------------- validación ------------------------------ */

function maxDecimalsOk(n: number, max: number): boolean {
    const s = String(n);
    if (s.includes('e') || s.includes('E')) return false;
    const i = s.indexOf('.');
    return i === -1 ? true : s.length - i - 1 <= max;
}

function parseCurrency(v: unknown): Currency | null {
    return v === 'EUR' || v === 'USD' ? v : null;
}

function parseClientOrderId(v: unknown): string | null {
    if (typeof v !== 'string') return null;
    const id = v.trim();
    return CLIENT_ORDER_RE.test(id) ? id : null;
}

function parseExecutedAt(v: unknown): number | null {
    if (typeof v !== 'number' || !Number.isInteger(v)) return null;
    if (v < MIN_EXECUTED_AT_MS) return null; // ms epoch; segundos serían ~1e9
    if (v > Date.now() + MAX_FUTURE_MS) return null;
    return v;
}

function parsePrice(v: unknown): number | null {
    if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0 || v > MAX_PRICE) return null;
    return maxDecimalsOk(v, MAX_PRICE_DECIMALS) ? v : null;
}

function parseQuantity(v: unknown): number | null {
    if (typeof v !== 'number' || !Number.isInteger(v) || v < 1 || v > MAX_QUANTITY) return null;
    return v;
}

function parseFee(v: unknown): number | null {
    if (v === undefined || v === null) return 0;
    if (typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > MAX_PRICE) return null;
    return maxDecimalsOk(v, 2) ? v : null;
}

function parseName(v: unknown, fallback: string): string {
    if (typeof v !== 'string') return fallback;
    const clean = v.replace(/[\u0000-\u001f]/g, '').trim().slice(0, 120);
    return clean || fallback;
}

type ParsedOrder = {
    instrument: Instrument;
    side: 'buy' | 'sell';
    openClose: 'open' | 'close';
    quantity: number;
    price: number;
    currency: Currency;
    fee: number;
    executedAt: number;
    clientOrderId: string;
};

function parseOrder(raw: unknown): ParsedOrder | ManualDemoFailure {
    if (!raw || typeof raw !== 'object') return failure('La orden debe ser un objeto.', 'order');
    const o = raw as Record<string, unknown>;
    const clientOrderId = parseClientOrderId(o.clientOrderId);
    if (!clientOrderId) return failure('clientOrderId debe ser una cadena de 8 a 80 caracteres (letras, dígitos, - y _).', 'clientOrderId');
    const side = o.side === 'buy' || o.side === 'sell' ? o.side : null;
    if (!side) return failure("side debe ser 'buy' o 'sell'.", 'side');
    const quantity = parseQuantity(o.quantity);
    if (quantity === null) return failure('La cantidad debe ser un entero entre 1 y 1.000.000 (sin fracciones en fase 1).', 'quantity');
    const price = parsePrice(o.price);
    if (price === null) return failure('El precio debe ser mayor que 0, con 4 decimales como máximo.', 'price');
    const currency = parseCurrency(o.currency);
    if (!currency) return failure("La divisa debe ser 'EUR' o 'USD'.", 'currency');
    const fee = parseFee(o.fee);
    if (fee === null) return failure('La comisión no puede ser negativa y admite 2 decimales como máximo.', 'fee');
    const executedAt = parseExecutedAt(o.executedAt);
    if (executedAt === null) {
        return failure('executedAt debe ser la fecha de ejecución en milisegundos epoch UTC, no futura.', 'executedAt');
    }
    const inst = o.instrument;
    if (!inst || typeof inst !== 'object') return failure('Falta el instrumento.', 'instrument');
    const i = inst as Record<string, unknown>;
    if (i.kind === 'accion') {
        const symbol = typeof i.symbol === 'string' ? i.symbol.trim().toUpperCase() : '';
        if (!SYMBOL_RE.test(symbol)) return failure('Símbolo de acción inválido (letras, dígitos, punto y guion; máx. 20).', 'symbol');
        return {
            instrument: { kind: 'accion', symbol, name: parseName(i.name, symbol) },
            side,
            openClose: side === 'buy' ? 'open' : 'close',
            quantity, price, currency, fee, executedAt, clientOrderId,
        };
    }
    if (i.kind === 'opcion') {
        if (!i.contract || typeof i.contract !== 'object') return failure('La opción necesita su contrato completo.', 'contract');
        const openClose = o.openClose === 'open' || o.openClose === 'close' ? o.openClose : null;
        if (!openClose) return failure("En opciones, openClose debe ser 'open' o 'close'.", 'openClose');
        const c = i.contract as OptionContract;
        return {
            instrument: {
                kind: 'opcion',
                contract: c,
                name: parseName(i.name, `${String(c.underlying ?? '').toUpperCase()} ${String(c.expiry ?? '')} ${String(c.strike ?? '')} ${c.callPut === 'put' ? 'Put' : 'Call'}`),
            },
            side, openClose, quantity, price, currency, fee, executedAt, clientOrderId,
        };
    }
    return failure("instrument.kind debe ser 'accion' u 'opcion'.", 'instrument');
}

type ParsedFx = {
    from: Currency;
    to: Currency;
    amount: number;
    rate: number;
    executedAt: number;
    clientOrderId: string;
};

function parseFx(raw: unknown): ParsedFx | ManualDemoFailure {
    if (!raw || typeof raw !== 'object') return failure('La conversión debe ser un objeto.', 'fx');
    const o = raw as Record<string, unknown>;
    const clientOrderId = parseClientOrderId(o.clientOrderId);
    if (!clientOrderId) return failure('clientOrderId debe ser una cadena de 8 a 80 caracteres (letras, dígitos, - y _).', 'clientOrderId');
    const from = parseCurrency(o.from);
    const to = parseCurrency(o.to);
    if (!from) return failure("La divisa origen debe ser 'EUR' o 'USD'.", 'from');
    if (!to) return failure("La divisa destino debe ser 'EUR' o 'USD'.", 'to');
    if (from === to) return failure('Origen y destino no pueden ser la misma divisa: convertir EUR en EUR crearía dinero ficticio.', 'to');
    const amount =
        typeof o.amount === 'number' && Number.isFinite(o.amount) && o.amount > 0 && o.amount <= 100_000_000 && maxDecimalsOk(o.amount, 2)
            ? o.amount
            : null;
    if (amount === null) return failure('El importe debe ser mayor que 0, con 2 decimales como máximo.', 'amount');
    const rate = typeof o.rate === 'number' && Number.isFinite(o.rate) && o.rate > 0 && o.rate <= 1000 && maxDecimalsOk(o.rate, MAX_RATE_DECIMALS) ? o.rate : null;
    if (rate === null) return failure('El tipo de cambio debe ser mayor que 0, con 6 decimales como máximo.', 'rate');
    const executedAt = parseExecutedAt(o.executedAt);
    if (executedAt === null) return failure('executedAt debe ser la fecha en milisegundos epoch UTC, no futura.', 'executedAt');
    return { from, to, amount, rate, executedAt, clientOrderId };
}

/* --------------------------- estado y libro ---------------------------- */

async function readLedger(userId: string, session?: ClientSession): Promise<{ state: AccountState; entries: LedgerEntry[] }> {
    const query = ManualDemoTrade.find({ userId, status: 'filled' }).sort({ executedAt: 1, _id: 1 });
    if (session) query.session(session);
    const docs = (await query) as unknown as ManualDemoTradeDoc[];
    const { entries, violations } = docsToLedger(docs);
    const state = computeManualDemoAccount(STARTING_CASH, entries);
    return { state: { ...state, violations: [...violations, ...state.violations] }, entries };
}

async function ensureAccount(userId: string): Promise<void> {
    const existing = await ManualDemoAccount.findOne({ userId });
    if (existing) return;
    try {
        await ManualDemoAccount.create([{ userId }]);
    } catch (error) {
        // Dos primeras visitas a la vez: el índice único ya la creó la otra.
        if ((error as { code?: number })?.code !== 11000) throw error;
    }
}

class VersionConflictError extends Error {
    constructor() {
        super('version conflict');
        this.name = 'VersionConflictError';
    }
}

/** La validación temporal tras la inserción real descuadró el libro: abortar. */
class TemporalDivergenceError extends Error {
    public readonly detail: string;
    constructor(detail: string) {
        super(detail);
        this.name = 'TemporalDivergenceError';
        this.detail = detail;
    }
}

/**
 * Graba un rechazo en escritura SEPARADA e idempotente: si otro reintento
 * (u otra petición con el mismo clientOrderId) ya grabó el resultado, se
 * devuelve lo persistido ('duplicate'), nunca una segunda fila.
 */
async function recordRejection(
    userId: string,
    clientOrderId: string,
    docFor: DocBuilder,
    reason: string,
    matches: (stored: ManualDemoTradeDoc) => boolean,
): Promise<TxnOutcome> {
    try {
        await ManualDemoTrade.create([docFor('rejected', reason)]);
    } catch (error) {
        if (!isDuplicateKey(error)) throw error;
    }
    const stored = await ManualDemoTrade.findOne({ userId, clientOrderId });
    const { state } = await readLedger(userId);
    if (stored && !matches(stored)) {
        // Carrera con el mismo clientOrderId pero OTRO payload: no es un
        // duplicado; es un conflicto explícito que no graba ni reinterpreta.
        throw new PayloadConflictError();
    }
    if (stored && stored.status === 'filled') {
        return { outcome: 'duplicate', reason: null, state };
    }
    if (stored && stored.status === 'rejected') {
        // Carrera mismo clientOrderId y mismo payload: el ganador ya grabó el
        // rechazo; se devuelve el reason PERSISTIDO, no el de este intento.
        return { outcome: 'rejected', reason: stored.rejectReason ?? reason, state };
    }
    return { outcome: 'rejected', reason, state };
}

/** El clientOrderId persistido pertenece a OTRO payload: conflicto, no duplicado. */
class PayloadConflictError extends Error {
    constructor() {
        super('manual-demo: clientOrderId reutilizado con una operación distinta');
        this.name = 'PayloadConflictError';
    }
}

function isDuplicateKey(error: unknown): boolean {
    return (error as { code?: number })?.code === 11000;
}

function isTxnUnsupported(error: unknown): boolean {
    const msg = error instanceof Error ? error.message : String(error);
    return /replica set|Transaction numbers|transactions are not supported/i.test(msg);
}

type TxnDecision = { kind: 'fill'; entry: LedgerEntry } | { kind: 'reject'; reason: string };

type DocBuilder = (status: 'filled' | 'rejected', reason: string | null) => Record<string, unknown>;

type TxnOutcome = { outcome: 'filled' | 'rejected' | 'duplicate'; reason: string | null; state: AccountState };

/**
 * Lee el libro DENTRO de una transacción, decide fill o rechazo; el fill se
 * inserta y se RELEE el libro persistido (orden executedAt, createdAt, _id)
 * para revalidar: cualquier violation nueva aborta sin fill ni caché y el
 * rechazo se graba aparte (idempotente). La caché y la versión solo se
 * actualizan al confirmar un fill, con escritura condicional
 * { userId, version }: dos órdenes concurrentes en la misma cuenta chocan
 * (write conflict) y la perdedora reintenta desde cero. Sin transacciones
 * no hay escritura.
 */
async function executeLedgerChange(
    userId: string,
    clientOrderId: string,
    decide: (state: AccountState) => TxnDecision,
    docFor: DocBuilder,
    matches: (stored: ManualDemoTradeDoc) => boolean,
): Promise<TxnOutcome> {
    let lastConflict: VersionConflictError | null = null;
    for (let attempt = 1; attempt <= MAX_TXN_ATTEMPTS; attempt++) {
        const conn = await connectToDatabase();
        // null solo es posible durante el build; en runtime es un invariante.
        if (!conn) throw new Error('manual-demo: conexión a MongoDB no disponible en runtime');
        const session = await conn.startSession();
        try {
            let outcome: TxnOutcome | null = null;
            await session.withTransaction(async () => {
                const account = await ManualDemoAccount.findOne({ userId }).session(session);
                if (!account) throw new Error('manual-demo: cuenta no encontrada tras ensureAccount');
                const { state } = await readLedger(userId, session);
                const decision = decide(state);
                if (decision.kind === 'reject') {
                    await ManualDemoTrade.create([docFor('rejected', decision.reason)], { session });
                    outcome = { outcome: 'rejected', reason: decision.reason, state };
                    return;
                }
                // Se inserta el fill PRIMERO y se RELEE el libro dentro de la
                // misma transacción (visible para sí misma): la validación se
                // hace sobre el orden persistido REAL (executedAt, createdAt,
                // _id), no sobre un cálculo previo en memoria. Si el replay completo
                // produce CUALQUIER violation nueva (de esta operación o de
                // una posterior que quedaría descuadrada), la transacción
                // aborta: no queda fill ni cambio de caché, y el rechazo se
                // graba aparte de forma idempotente.
                await ManualDemoTrade.create([docFor('filled', null)], { session });
                const post = await readLedger(userId, session);
                const baseline = new Set(state.violations);
                const freshViolations = post.state.violations.filter((v) => !baseline.has(v));
                if (freshViolations.length > 0) {
                    throw new TemporalDivergenceError(
                        `La operación no cuadra en su fecha de ejecución (el libro se recalcula por fecha, no por orden de alta): ${freshViolations[0]}`,
                    );
                }
                // El bump de versión SOLO confirma fills; los rechazos no
                // cambian el estado y no lo tocan.
                const updated = await ManualDemoAccount.findOneAndUpdate(
                    { userId, version: account.version },
                    { $set: { cashEUR: post.state.cashByCurrency.EUR, cashUSD: post.state.cashByCurrency.USD }, $inc: { version: 1 } },
                    { session, returnDocument: 'after' },
                );
                if (!updated) throw new VersionConflictError();
                outcome = { outcome: 'filled', reason: null, state: post.state };
            });
            if (!outcome) throw new Error('manual-demo: transacción sin resultado');
            return outcome;
        } catch (error) {
            if (error instanceof TemporalDivergenceError) {
                return await recordRejection(userId, clientOrderId, docFor, error.detail, matches);
            }
            if (error instanceof VersionConflictError) {
                lastConflict = error;
                continue;
            }
            throw error;
        } finally {
            await session.endSession();
        }
    }
    throw lastConflict ?? new VersionConflictError();
}

/* --------------------------- construir docs ---------------------------- */

function orderDocFor(parsed: ParsedOrder, userId: string): DocBuilder {
    return (status, reason) => ({
        userId,
        clientOrderId: parsed.clientOrderId,
        kind: parsed.instrument.kind,
        symbol: parsed.instrument.kind === 'accion' ? parsed.instrument.symbol : parsed.instrument.contract.underlying.toUpperCase(),
        name: parsed.instrument.name,
        contract: parsed.instrument.kind === 'opcion' ? parsed.instrument.contract : null,
        side: parsed.side,
        openClose: parsed.openClose,
        fxFrom: null,
        fxTo: null,
        quantity: parsed.quantity,
        status,
        fillPrice: status === 'filled' ? parsed.price : null,
        currency: parsed.currency,
        fee: status === 'filled' ? parsed.fee : 0,
        fillSource: 'manual-simulado',
        executedAt: status === 'filled' ? new Date(parsed.executedAt) : null,
        requestPayload: status === 'rejected' ? orderSnapshotFor(parsed) : null,
        rejectReason: reason,
    });
}

function fxDocFor(parsed: ParsedFx, userId: string): DocBuilder {
    return (status, reason) => ({
        userId,
        clientOrderId: parsed.clientOrderId,
        kind: 'fx',
        symbol: `${parsed.from}${parsed.to}`,
        name: `Conversión manual ${parsed.from}→${parsed.to}`,
        contract: null,
        side: 'buy',
        openClose: 'open',
        fxFrom: parsed.from,
        fxTo: parsed.to,
        quantity: parsed.amount,
        status,
        fillPrice: status === 'filled' ? parsed.rate : null,
        currency: parsed.from,
        fee: 0,
        fillSource: 'manual-simulado',
        executedAt: status === 'filled' ? new Date(parsed.executedAt) : null,
        requestPayload: status === 'rejected' ? fxSnapshotFor(parsed) : null,
        rejectReason: reason,
    });
}

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

/** Huella comparable del payload: las filas RECHAZADAS no persisten precio,
 * comisión ni fecha de ejecución (fillPrice/fee/executedAt quedan null/0 en
 * orderDocFor), así que esos campos solo se comparan cuando la fila original
 * es un fill. La identidad del instrumento, lado, fase, cantidad y divisa
 * siempre se comparan. */
/* ----- snapshot del payload pedido (fix-2): rechazos comparables ----- */

type OrderSnapshot = {
    v: 1;
    kind: 'accion' | 'opcion';
    symbol: string | null;
    contractKey: string | null;
    side: 'buy' | 'sell';
    openClose: 'open' | 'close';
    quantity: number;
    currency: Currency;
    price: number;
    fee: number;
    executedAtMs: number;
};

type FxSnapshot = { v: 1; kind: 'fx'; from: Currency; to: Currency; amount: number; rate: number; executedAtMs: number };

function orderSnapshotFor(p: ParsedOrder): OrderSnapshot {
    return {
        v: 1,
        kind: p.instrument.kind,
        symbol: p.instrument.kind === 'accion' ? p.instrument.symbol : null,
        contractKey: p.instrument.kind === 'opcion' ? instrumentKey(p.instrument) : null,
        side: p.side,
        openClose: p.openClose,
        quantity: p.quantity,
        currency: p.currency,
        price: p.price,
        fee: p.fee,
        executedAtMs: p.executedAt,
    };
}

function fxSnapshotFor(p: ParsedFx): FxSnapshot {
    return { v: 1, kind: 'fx', from: p.from, to: p.to, amount: p.amount, rate: p.rate, executedAtMs: p.executedAt };
}

/** Shape del Mixed persistido: cualquier cosa inesperada = desconocido (null), NUNCA excepción. */
function asOrderSnapshot(raw: unknown): OrderSnapshot | null {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    const s = raw as Record<string, unknown>;
    if (s.v !== 1) return null;
    if (s.kind !== 'accion' && s.kind !== 'opcion') return null;
    if (s.side !== 'buy' && s.side !== 'sell') return null;
    if (s.openClose !== 'open' && s.openClose !== 'close') return null;
    if (s.currency !== 'EUR' && s.currency !== 'USD') return null;
    if (s.kind === 'accion' && typeof s.symbol !== 'string') return null;
    if (s.kind === 'opcion' && typeof s.contractKey !== 'string') return null;
    for (const k of ['quantity', 'price', 'fee', 'executedAtMs'] as const) {
        if (typeof s[k] !== 'number' || !Number.isFinite(s[k])) return null;
    }
    return s as unknown as OrderSnapshot;
}

function asFxSnapshot(raw: unknown): FxSnapshot | null {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    const s = raw as Record<string, unknown>;
    if (s.v !== 1 || s.kind !== 'fx') return null;
    if ((s.from !== 'EUR' && s.from !== 'USD') || (s.to !== 'EUR' && s.to !== 'USD')) return null;
    for (const k of ['amount', 'rate', 'executedAtMs'] as const) {
        if (typeof s[k] !== 'number' || !Number.isFinite(s[k])) return null;
    }
    return s as unknown as FxSnapshot;
}

function sameOrderSnapshot(a: OrderSnapshot, b: OrderSnapshot): boolean {
    return a.kind === b.kind && a.symbol === b.symbol && a.contractKey === b.contractKey
        && a.side === b.side && a.openClose === b.openClose && a.quantity === b.quantity
        && a.currency === b.currency && a.price === b.price && a.fee === b.fee && a.executedAtMs === b.executedAtMs;
}

function sameFxSnapshot(a: FxSnapshot, b: FxSnapshot): boolean {
    return a.from === b.from && a.to === b.to && a.amount === b.amount && a.rate === b.rate && a.executedAtMs === b.executedAtMs;
}

function sameOrderPayload(stored: ManualDemoTradeDoc, p: ParsedOrder): boolean {
    if (stored.kind !== p.instrument.kind) return false;
    if (stored.side !== p.side || stored.openClose !== p.openClose) return false;
    if (stored.quantity !== p.quantity || stored.currency !== p.currency) return false;
    if (p.instrument.kind === 'accion') {
        if (stored.symbol !== p.instrument.symbol) return false;
    } else {
        const key = stored.contract
            ? instrumentKey({ kind: 'opcion', contract: stored.contract as OptionContract, name: '' })
            : null;
        if (key !== instrumentKey(p.instrument)) return false;
    }
    if (stored.status === 'filled') {
        if (stored.fillPrice !== p.price || stored.fee !== p.fee) return false;
        const t = stored.executedAt ? stored.executedAt.getTime() : null;
        return t === p.executedAt;
    }
    // Rechazada con snapshot válido (fix-2): comparación completa del payload pedido.
    const snap = asOrderSnapshot(stored.requestPayload);
    if (snap) return sameOrderSnapshot(snap, orderSnapshotFor(p));
    // LEGACY (sin snapshot válido): la igualdad completa es desconocida; solo el
    // subconjunto persistido arriba prueba igualdad. Precio/fee/fecha NO se afirman.
    return true;
}

function sameFxPayload(stored: ManualDemoTradeDoc, p: ParsedFx): boolean {
    if (stored.kind !== 'fx' || stored.fxFrom !== p.from || stored.fxTo !== p.to) return false;
    if (stored.quantity !== p.amount) return false;
    if (stored.status === 'filled') {
        if (stored.fillPrice !== p.rate) return false;
        const t = stored.executedAt ? stored.executedAt.getTime() : null;
        return t === p.executedAt;
    }
    // Rechazada con snapshot válido (fix-2): comparación completa del payload pedido.
    const snap = asFxSnapshot(stored.requestPayload);
    if (snap) return sameFxSnapshot(snap, fxSnapshotFor(p));
    // LEGACY: igualdad completa desconocida; solo el subconjunto persistido prueba igualdad.
    return true;
}

async function duplicateResult(
    userId: string,
    clientOrderId: string,
    matches: (stored: ManualDemoTradeDoc) => boolean,
): Promise<ManualDemoOrderResult | null> {
    const stored = await ManualDemoTrade.findOne({ userId, clientOrderId });
    if (!stored) return null;
    // La clave de idempotencia pertenece a UN payload: reusarla con otra
    // operación no es un duplicado silencioso sino un error explícito que no
    // graba nada (la UI genera un id nuevo al recargar el formulario).
    if (!matches(stored)) {
        return failure('Ese identificador de orden ya se usó con una operación distinta. Recarga la página para generar uno nuevo.', 'clientOrderId');
    }
    const { state } = await readLedger(userId);
    return {
        ok: true,
        outcome: 'duplicate',
        reason: stored.status === 'rejected' ? stored.rejectReason : null,
        state: toView(state),
    };
}

function unexpectedError(scope: string, error: unknown): ManualDemoFailure {
    if (isTxnUnsupported(error)) {
        console.error(`${scope}: el despliegue no soporta transacciones`, error);
        return failure('La cuenta demo no puede operar con seguridad en este despliegue (sin transacciones). Aviso registrado.');
    }
    console.error(`${scope}:`, error);
    return failure('No se pudo completar la operación. Inténtalo de nuevo en unos minutos.');
}

/* ---------------------------- acciones --------------------------------- */

/** Estado de la cuenta demo del usuario de la sesión (crea la cuenta si no existe). */
export async function getManualDemoAccount(): Promise<ManualDemoAccountResult> {
    const user = await requireDemoUser();
    if (!isDemoUser(user)) return user;
    try {
        await connectToDatabase();
        await ensureAccount(user.id);
        const { state } = await readLedger(user.id);
        // Reparación de la caché de saldos si se descuadró del libro (la
        // fuente de verdad es el libro; la caché solo acelera lecturas).
        const account = await ManualDemoAccount.findOne({ userId: user.id });
        if (account && (account.cashEUR !== state.cashByCurrency.EUR || account.cashUSD !== state.cashByCurrency.USD)) {
            state.violations = [
                `Caché de saldos descuadrada (cuenta ${money(account.cashEUR)} EUR / ${money(account.cashUSD)} USD frente a libro ${money(state.cashByCurrency.EUR)} EUR / ${money(state.cashByCurrency.USD)} USD); reparada desde el libro.`,
                ...state.violations,
            ];
            await ManualDemoAccount.findOneAndUpdate(
                { userId: user.id, version: account.version },
                { $set: { cashEUR: state.cashByCurrency.EUR, cashUSD: state.cashByCurrency.USD }, $inc: { version: 1 } },
                { returnDocument: 'after' },
            );
        }
        return { ok: true, state: toView(state) };
    } catch (error) {
        return unexpectedError('getManualDemoAccount', error);
    }
}

export type ManualDemoValuationResult =
    // Señales estructuradas de fallo transitorio para el backoff del cliente:
    // - listingUnavailable: había símbolos a valorar pero el listado US de
    //   divisas no respondió (no se pidió ninguna cotización; filas N/D).
    // - quoteFetchFailed: había símbolos verificables y TODAS las consultas
    //   de cotización fallaron (429, red, timeout). Un dato genuinamente
    //   ausente o viejo (fetch OK, saneado a null) NO lo activa.
    // - retryAfterSeconds: Retry-After expuesto por el proveedor en un fallo
    //   (p. ej. 429); el cliente no debe reintentar antes. null si no vino.
    | { ok: true; valuation: DemoValuation; asOf: number; listingUnavailable: boolean; quoteFetchFailed: boolean; retryAfterSeconds: number | null }
    | ManualDemoFailure;

const MAX_VALUATION_SYMBOLS = 25;
/**
 * Cotización SOLO de Finnhub (/quote) con la frescura validada por
 * sanitizeFinnhubQuote (stale => null). Deliberadamente NO usa getStockQuote:
 * ese camino cae a Yahoo Finance si Finnhub falla, y aquí nunca debe haber
 * ninguna llamada a Yahoo.
 * fetchFailed distingue el fallo transitorio (sin clave, HTTP no-OK como un
 * 429, red o timeout) del dato genuinamente ausente o viejo (respuesta OK
 * que el saneado descarta): solo el primero debe armar el backoff del
 * cliente. retryAfterSeconds recoge el Retry-After cuando el proveedor lo
 * expone en un no-OK (cabecera estándar de throttle, en segundos).
 */
// Misma forma que QuoteFetchAttempt del quote-cache (quote saneado | null,
// fetchFailed, retryAfterSeconds): la valoración trabaja con el intento
// enriquecido (fetchedAt/saturated) que devuelve la caché.
type QuoteAttempt = QuoteFetchAttempt;

async function finnhubOnlyQuote(symbol: string, signal?: AbortSignal): Promise<QuoteAttempt> {
    const token = process.env.FINNHUB_API_KEY;
    if (!token) return { quote: null, fetchFailed: true, retryAfterSeconds: null };
    try {
        const base = process.env.FINNHUB_BASE_URL || 'https://finnhub.io/api/v1';
        const response = await fetch(`${base}/quote?symbol=${encodeURIComponent(symbol)}&token=${encodeURIComponent(token)}`, {
            cache: 'no-store',
            // El timeout de la caché ABORTA de verdad (su señal llega hasta
            // este fetch); el tope propio de 8 s se mantiene en paralelo.
            signal: signal ? combineAbortSignals(signal, 8_000) : AbortSignal.timeout(8_000),
        });
        if (!response.ok) {
            const retryAfter = Number.parseInt(response.headers.get('retry-after') ?? '', 10);
            return { quote: null, fetchFailed: true, retryAfterSeconds: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null };
        }
        return { quote: sanitizeFinnhubQuote(await response.json()), fetchFailed: false, retryAfterSeconds: null };
    } catch {
        return { quote: null, fetchFailed: true, retryAfterSeconds: null };
    }
}

/**
 * Caché dedupe de cotizaciones PÚBLICAS (lib/market/quote-cache.ts), una
 * instancia por proceso: mismo símbolo en ráfaga (renders concurrentes,
 * re-polls dentro del TTL de 20 s) => UN fetch; backoff/Retry-After
 * compartido tras fallos (un 429 frena también la siguiente valoración).
 * SOLO cotizaciones: el libro se relee en CADA llamada (readLedger abajo),
 * así que cash/posiciones nunca salen de caché. No es protección global de
 * cuota: cada instancia serverless lleva la suya.
 */
const valuationQuoteCache = createQuoteCache();

const LISTING_TTL_MS = 6 * 3_600_000;
let usListing: { at: number; map: Map<string, string> } | null = null;
let listingInflight: Promise<Map<string, string> | null> | null = null;

/**
 * Listado US de Finnhub (/stock/symbol?exchange=US, tier gratis; campo
 * currency) para verificar la divisa. Una sola descarga a la vez: las
 * llamadas concurrentes comparten la misma promesa. Un fallo (red, 429,
 * vacio) devuelve null y NO se cachea, asi que la siguiente invocacion
 * reintenta; un listado correcto se reutiliza 6 h en memoria.
 */
function getUsListing(): Promise<Map<string, string> | null> {
    const token = process.env.FINNHUB_API_KEY;
    if (!token) return Promise.resolve(null);
    if (usListing && Date.now() - usListing.at <= LISTING_TTL_MS) return Promise.resolve(usListing.map);
    if (listingInflight) return listingInflight;
    listingInflight = (async () => {
        try {
            const base = process.env.FINNHUB_BASE_URL || 'https://finnhub.io/api/v1';
            const response = await fetch(`${base}/stock/symbol?exchange=US&token=${encodeURIComponent(token)}`, {
                cache: 'no-store',
                signal: AbortSignal.timeout(15_000),
            });
            if (!response.ok) return null;
            const map = parseListingCurrencies(await response.json());
            if (map.size === 0) return null;
            usListing = { at: Date.now(), map };
            return map;
        } catch {
            return null;
        } finally {
            listingInflight = null;
        }
    })();
    return listingInflight;
}

/**
 * Valoración BAJO DEMANDA de las posiciones abiertas con cotizaciones reales
 * (Finnhub /quote directo, validada por frescura; sin fallback a Yahoo ni a
 * getStockQuote). Las cotizaciones pasan por valuationQuoteCache (dedupe por
 * símbolo, TTL 20 s, revalidación de frescura al servir, backoff compartido
 * tras fallos): una ráfaga de valoraciones en la misma ventana comparte los
 * fetches; la hora de cada fila sigue siendo la del proveedor (quote.t).
 * asOf = min(fetchedAt) de las cotizaciones usadas (la más vieja servida;
 * Date.now() si no hubo ninguna) para que la UI no maquille datos de caché
 * como recién pedidos. El libro NO se cachea: posiciones y cash se releen
 * del ledger en cada llamada y un fill se refleja al instante.
 * Sin cotización => N/D por posición; nunca se usa el precio de
 * un fill como precio de mercado. Más de 25 símbolos distintos: los
 * sobrantes salen "No consultada: límite de 25 símbolos por consulta".
 * Estrictamente de solo lectura: ni siquiera crea la cuenta vacía (a
 * diferencia de getManualDemoAccount); el libro vacío valora a "sin posiciones".
 */
export async function getManualDemoValuation(): Promise<ManualDemoValuationResult> {
    const user = await requireDemoUser();
    if (!isDemoUser(user)) return user;
    try {
        await connectToDatabase();
        const { state } = await readLedger(user.id);
        const positions = state.positions.map((p) => ({
            instrumentKey: p.instrumentKey,
            name: p.name,
            kind: p.kind,
            currency: p.currency,
            quantity: p.quantity,
            avgCost: p.avgCost,
        }));
        const allSymbols = [
            ...new Set(
                positions
                    .filter((p) => p.kind === 'accion')
                    .map((p) => symbolFromKey(p.instrumentKey))
                    .filter((s): s is string => Boolean(s))
                    .map((s) => s.toUpperCase()),
            ),
        ];
        const symbols = allSymbols.slice(0, MAX_VALUATION_SYMBOLS);
        const notQueried = new Set(allSymbols.slice(MAX_VALUATION_SYMBOLS));
        const quotes: Record<string, ValuationQuote | null> = {};
        // Un solo lookup de divisa ANTES del reparto: sin listado no se piden
        // cotizaciones (serian inutiles: sin divisa verificada la fila es N/D).
        const listing = symbols.length > 0 ? await getUsListing() : null;
        const verifiable = listing ? symbols.filter((s) => listing.has(s)) : [];
        const settled = await Promise.allSettled(verifiable.map((symbol) => valuationQuoteCache.getQuote(symbol, finnhubOnlyQuote)));
        for (const symbol of symbols) quotes[symbol] = null;
        const currencyUnverified = new Set(symbols.filter((s) => !verifiable.includes(s)));
        let fetchFailures = 0;
        let retryAfterSeconds: number | null = null;
        let oldestQuoteAt: number | null = null;
        verifiable.forEach((symbol, i) => {
            const r = settled[i];
            const attempt: CachedQuote =
                r.status === 'fulfilled'
                    ? r.value
                    : { quote: null, fetchFailed: true, retryAfterSeconds: null, fetchedAt: null, saturated: false };
            quotes[symbol] = attempt.quote ? { ...attempt.quote, currency: listing?.get(symbol) ?? null } : null;
            if (attempt.quote && attempt.fetchedAt !== null) oldestQuoteAt = Math.min(oldestQuoteAt ?? Infinity, attempt.fetchedAt);
            if (attempt.fetchFailed) {
                fetchFailures += 1;
                if (attempt.retryAfterSeconds !== null) retryAfterSeconds = Math.max(retryAfterSeconds ?? 0, attempt.retryAfterSeconds);
            }
        });
        return {
            ok: true,
            valuation: valuePositions(positions, quotes, { notQueried, currencyUnverified, locale: await requestLocale() }),
            // min(fetchedAt): la cotización más vieja servida manda (cambio
            // de semántica documentado arriba: antes era Date.now() siempre).
            asOf: oldestQuoteAt ?? Date.now(),
            listingUnavailable: symbols.length > 0 && listing === null,
            quoteFetchFailed: verifiable.length > 0 && fetchFailures === verifiable.length,
            retryAfterSeconds,
        };
    } catch (error) {
        return unexpectedError('getManualDemoValuation', error);
    }
}

/** Historial de la cuenta demo (fills y rechazos), más reciente primero. */
export async function getManualDemoOrders(): Promise<ManualDemoOrdersResult> {
    const user = await requireDemoUser();
    if (!isDemoUser(user)) return user;
    try {
        await connectToDatabase();
        const docs = (await ManualDemoTrade.find({ userId: user.id }).sort({ createdAt: -1, _id: -1 })) as unknown as ManualDemoTradeDoc[];
        return { ok: true, orders: docs.map(toRow) };
    } catch (error) {
        return unexpectedError('getManualDemoOrders', error);
    }
}

/**
 * Registra una orden manual simulada (acción u opción). Toda validación de
 * saldo/posición se hace contra el libro DENTRO de la transacción: el
 * cliente nunca manda saldos "de confianza". Los rechazos quedan grabados
 * en el historial con su motivo (como un broker), no entran en la contabilidad.
 */
export async function placeManualOrder(raw: unknown): Promise<ManualDemoOrderResult> {
    const user = await requireDemoUser();
    if (!isDemoUser(user)) return user;
    const parsed = parseOrder(raw);
    if ('ok' in parsed) return parsed;
    try {
        await connectToDatabase();
        await ensureAccount(user.id);
        const duplicate = await duplicateResult(user.id, parsed.clientOrderId, (stored) => sameOrderPayload(stored, parsed));
        if (duplicate) return duplicate;

        const decide = (state: AccountState): TxnDecision => {
            const key = instrumentKey(parsed.instrument);
            const position = state.positions.find((p) => p.instrumentKey === key && p.currency === parsed.currency);
            if (parsed.instrument.kind === 'opcion') {
                const built = buildOptionFill({
                    contract: parsed.instrument.contract,
                    side: parsed.side,
                    openClose: parsed.openClose,
                    contracts: parsed.quantity,
                    premium: parsed.price,
                    currency: parsed.currency,
                    fee: parsed.fee,
                    executedAt: parsed.executedAt,
                    clientOrderId: parsed.clientOrderId,
                    heldContracts: position?.quantity ?? 0,
                    availableCash: state.cashByCurrency[parsed.currency],
                });
                if (!built.ok) return { kind: 'reject', reason: built.reason };
                return { kind: 'fill', entry: built.value };
            }
            const fill = toFill({
                instrument: parsed.instrument,
                side: parsed.side,
                openClose: parsed.openClose,
                quantity: parsed.quantity,
                price: parsed.price,
                currency: parsed.currency,
                fee: parsed.fee,
                executedAt: parsed.executedAt,
                clientOrderId: parsed.clientOrderId,
            });
            if (!fill) return { kind: 'reject', reason: 'Los datos de la orden no forman un fill válido.' };
            if (parsed.side === 'buy') {
                const cost = r2(parsed.quantity * parsed.price + parsed.fee);
                const cash = state.cashByCurrency[parsed.currency];
                if (cost > cash + 1e-9) {
                    return { kind: 'reject', reason: `Saldo ${parsed.currency} insuficiente: la compra cuesta ${money(cost)} y hay ${money(cash)}. Si es en USD, convierte EUR antes (conversión manual simulada).` };
                }
            } else {
                const held = position?.quantity ?? 0;
                if (held < parsed.quantity) {
                    return { kind: 'reject', reason: `No puedes vender ${parsed.quantity} acciones de ${parsed.instrument.symbol}: la posición en ${parsed.currency} es ${held}.` };
                }
                // Sin sobregiro: la comisión también debe caber en el cash que
                // queda tras abonar la venta (la compra ya lo chequea).
                const proceeds = r2(parsed.quantity * parsed.price);
                const cashAfterSale = state.cashByCurrency[parsed.currency] + proceeds;
                if (parsed.fee > cashAfterSale + 1e-9) {
                    return { kind: 'reject', reason: `La comisión (${money(parsed.fee)} ${parsed.currency}) supera el efectivo disponible tras la venta (${money(cashAfterSale)}): la demo no admite sobregiro.` };
                }
            }
            return { kind: 'fill', entry: fill };
        };

        const outcome = await executeLedgerChange(user.id, parsed.clientOrderId, decide, orderDocFor(parsed, user.id), (stored) => sameOrderPayload(stored, parsed));
        return { ok: true, outcome: outcome.outcome, reason: outcome.reason, state: toView(outcome.state) };
    } catch (error) {
        if (isDuplicateKey(error)) {
            const duplicate = await duplicateResult(user.id, parsed.clientOrderId, (stored) => sameOrderPayload(stored, parsed));
            if (duplicate) return duplicate;
        }
        if (error instanceof PayloadConflictError) {
            return failure('Ese identificador de orden ya se usó con una operación distinta. Recarga la página para generar uno nuevo.', 'clientOrderId');
        }
        if (error instanceof VersionConflictError) {
            return failure('La cuenta estaba procesando otra orden a la vez. Inténtalo de nuevo.');
        }
        return unexpectedError('placeManualOrder', error);
    }
}

/**
 * Conversión manual simulada EUR<->USD: el usuario introduce el tipo de
 * cambio; queda etiquetada como simulada. Sin conversión previa no hay
 * saldo para operar en la otra divisa (nada de fondos implícitos).
 */
export async function convertManualDemoCurrency(raw: unknown): Promise<ManualDemoOrderResult> {
    const user = await requireDemoUser();
    if (!isDemoUser(user)) return user;
    const parsed = parseFx(raw);
    if ('ok' in parsed) return parsed;
    try {
        await connectToDatabase();
        await ensureAccount(user.id);
        const duplicate = await duplicateResult(user.id, parsed.clientOrderId, (stored) => sameFxPayload(stored, parsed));
        if (duplicate) return duplicate;

        const decide = (state: AccountState): TxnDecision => {
            const cash = state.cashByCurrency[parsed.from];
            if (parsed.amount > cash + 1e-9) {
                return { kind: 'reject', reason: `Saldo ${parsed.from} insuficiente para convertir ${money(parsed.amount)}: hay ${money(cash)}.` };
            }
            const entry: FxConversion = {
                kind: 'fx',
                from: parsed.from,
                to: parsed.to,
                amountFrom: parsed.amount,
                rate: parsed.rate,
                executedAt: parsed.executedAt,
                source: 'manual-simulado',
                clientOrderId: parsed.clientOrderId,
            };
            return { kind: 'fill', entry };
        };

        const outcome = await executeLedgerChange(user.id, parsed.clientOrderId, decide, fxDocFor(parsed, user.id), (stored) => sameFxPayload(stored, parsed));
        return { ok: true, outcome: outcome.outcome, reason: outcome.reason, state: toView(outcome.state) };
    } catch (error) {
        if (isDuplicateKey(error)) {
            const duplicate = await duplicateResult(user.id, parsed.clientOrderId, (stored) => sameFxPayload(stored, parsed));
            if (duplicate) return duplicate;
        }
        if (error instanceof PayloadConflictError) {
            return failure('Ese identificador de orden ya se usó con una operación distinta. Recarga la página para generar uno nuevo.', 'clientOrderId');
        }
        if (error instanceof VersionConflictError) {
            return failure('La cuenta estaba procesando otra operación a la vez. Inténtalo de nuevo.');
        }
        return unexpectedError('convertManualDemoCurrency', error);
    }
}
