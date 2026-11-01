/**
 * Loader de soporte SOLO para manual-demo-actions.guard.test.ts.
 *
 * node --experimental-strip-types no resuelve el alias `@/` ni debe
 * arrancar el runtime Next (next/headers via require-user). Redirige:
 * - `@/lib/auth/require-user` -> stub con usuario fijo (misma semantica
 *   que E2E_AUTH_BYPASS=1; sin sesion si __MANUAL_DEMO_GUARD_USER__ es null).
 * - `@/database/mongoose` -> stub de conexion con sesiones/transacciones falsas.
 * - `@/database/models/manual-demo.model` -> colecciones en memoria con
 *   unicidad (userId, clientOrderId) y escritura condicional por version.
 * - `mongoose` -> stub de Types.ObjectId (cursor del historial paginado).
 * - `@/lib/research/backend-error-locale` -> requestLocale() = 'es' (sin petición).
 * - `@/lib/paper-trading/{types,accounting,options,ledger-adapter}` y
 *   `@/lib/market/{demo-valuation,quote-freshness}` ->
 *   ficheros REALES del repo (el codigo bajo test es el fuente real).
 */
const REAL = {
    '@/lib/format': '../lib/format.ts',
    '@/lib/paper-trading/types': '../lib/paper-trading/types.ts',
    '@/lib/paper-trading/accounting': '../lib/paper-trading/accounting.ts',
    '@/lib/paper-trading/options': '../lib/paper-trading/options.ts',
    '@/lib/paper-trading/ledger-adapter': '../lib/paper-trading/ledger-adapter.ts',
    '@/lib/market/demo-valuation': '../lib/market/demo-valuation.ts',
    '@/lib/market/quote-freshness': '../lib/market/quote-freshness.ts',
    '@/lib/market/quote-cache': '../lib/market/quote-cache.ts',
};

export async function resolve(specifier, context, nextResolve) {
    if (specifier === '@/lib/auth/require-user') return { url: 'guard-stub:require-user', shortCircuit: true };
    if (specifier === '@/database/mongoose') return { url: 'guard-stub:mongoose', shortCircuit: true };
    if (specifier === '@/database/models/manual-demo.model') return { url: 'guard-stub:manual-demo-model', shortCircuit: true };
    if (specifier === 'mongoose') return { url: 'guard-stub:mongoose-types', shortCircuit: true };
    if (specifier === '@/lib/research/backend-error-locale') return { url: 'guard-stub:request-locale', shortCircuit: true };
    if (REAL[specifier]) return { url: new URL(REAL[specifier], import.meta.url).href, shortCircuit: true };
    if (specifier.startsWith('@/')) throw new Error(`manual-demo guard loader: import no esperado: ${specifier}`);
    return nextResolve(specifier, context);
}

const REQUIRE_USER_STUB = [
    'export async function requireAuthenticatedUser() {',
    '    const u = globalThis.__MANUAL_DEMO_GUARD_USER__;',
    "    if (!u) { const e = new Error('User not authenticated'); e.name = 'AuthenticationError'; throw e; }",
    '    return u;',
    '}',
].join('\n');

const MONGOOSE_STUB = [
    'let startSessionError = null;',
    '// Las transacciones reales hacen ROLLBACK al abortar: el stub imita eso',
    '// con snapshot/restore, o un test de reintento veria escrituras fantasma.',
    'const modelPromise = import("@/database/models/manual-demo.model");',
    'export async function connectToDatabase() {',
    '    return {',
    '        startSession: async () => {',
    '            if (startSessionError) { const e = startSessionError; startSessionError = null; throw e; }',
    '            return {',
    '                withTransaction: async (cb) => {',
    '                    const model = await modelPromise;',
    '                    const snap = model.__snapshot();',
    '                    try { return await cb(); } catch (e) { model.__restore(snap); throw e; }',
    '                },',
    '                endSession: async () => {},',
    '            };',
    '        },',
    '    };',
    '}',
    'export function __setStartSessionError(e) { startSessionError = e; }',
].join('\n');

const MODEL_STUB = [
    'let accounts = [];',
    'let trades = [];',
    'let clockMs = Date.now();',
    'let idSeq = 0;',
    'let failVersionUpdates = 0;',
    'let dupNextTradeCreate = null;',
    'const clone = (d) => structuredClone(d);',
    'function makeQuery(getDocs) {',
    '    const q = {',
    '        session: () => q,',
    '        lean: () => q,',
    '        limit: (n) => makeQuery(() => getDocs().slice(0, n)),',
    '        sort: (spec) => {',
    '            const keys = Object.entries(spec);',
    '            const val = (d, f) => (d[f] instanceof Date ? d[f].getTime() : d[f]);',
    '            const docs = getDocs().slice().sort((a, b) => {',
    '                for (const [field, dir] of keys) {',
    '                    const av = val(a, field); const bv = val(b, field);',
    '                    const cmp = typeof av === "string" || typeof bv === "string" ? String(av).localeCompare(String(bv)) : av - bv;',
    '                    if (cmp !== 0) return cmp * (dir < 0 ? -1 : 1);',
    '                }',
    '                return 0;',
    '            });',
    '            return makeQuery(() => docs);',
    '        },',
    '        then: (r, j) => Promise.resolve(clone(getDocs())).then(r, j),',
    '    };',
    '    return q;',
    '}',
    'function makeOne(getDoc) {',
    '    const q = { session: () => q, lean: () => q, then: (r, j) => Promise.resolve(getDoc() ? clone(getDoc()) : null).then(r, j) };',
    '    return q;',
    '}',
    'const dupError = () => { const e = new Error("E11000 duplicate key error"); e.code = 11000; return e; };',
    '// Igualdad por VALOR (Date compara por ms; los ObjectId del stub por su',
    '// hex), $or/$and y operadores de comparacion: el historial paginado filtra',
    '// con cursor compuesto {createdAt, _id} y necesita la misma semantica.',
    'const scalar = (v) => {',
    '    if (v instanceof Date) return v.getTime();',
    '    if (v !== null && typeof v === "object" && "__oid" in v) return v.__oid;',
    '    return v;',
    '};',
    'const ltVal = (a, b) => (typeof a === "string" || typeof b === "string" ? String(a) < String(b) : a < b);',
    'const matchCond = (actual, cond) => {',
    '    if (cond !== null && typeof cond === "object" && !(cond instanceof Date) && !Array.isArray(cond) && !("__oid" in cond)) {',
    '        return Object.entries(cond).every(([op, v]) => {',
    '            const a = scalar(actual); const b = scalar(v);',
    '            if (op === "$lt") return ltVal(a, b);',
    '            if (op === "$lte") return a === b || ltVal(a, b);',
    '            if (op === "$gt") return ltVal(b, a);',
    '            if (op === "$gte") return a === b || ltVal(b, a);',
    '            throw new Error("stub match: operador no soportado: " + op);',
    '        });',
    '    }',
    '    return scalar(actual) === scalar(cond);',
    '};',
    'const match = (doc, filter) => Object.entries(filter).every(([k, v]) => {',
    '    if (k === "$or") return v.some((sub) => match(doc, sub));',
    '    if (k === "$and") return v.every((sub) => match(doc, sub));',
    '    return matchCond(doc[k], v);',
    '});',
    'export const MANUAL_DEMO_STARTING_CASH_EUR = 100000;',
    'export const ManualDemoAccount = {',
    '    findOne: (filter) => makeOne(() => accounts.find((a) => match(a, filter)) ?? null),',
    '    create: async (docs) => {',
    '        const out = [];',
    '        for (const doc of docs) {',
    '            if (accounts.some((a) => a.userId === doc.userId)) throw dupError();',
    '            const row = { cashEUR: 100000, cashUSD: 0, version: 0, ...doc, _id: "acc-" + String(++idSeq).padStart(6, "0"), createdAt: new Date(++clockMs), updatedAt: new Date(clockMs) };',
    '            accounts.push(row); out.push(clone(row));',
    '        }',
    '        return out;',
    '    },',
    '    findOneAndUpdate: async (filter, update) => {',
    '        if (failVersionUpdates > 0) { failVersionUpdates--; return null; }',
    '        const row = accounts.find((a) => match(a, filter)) ?? null;',
    '        if (!row) return null;',
    '        Object.assign(row, update.$set ?? {});',
    '        for (const [k, v] of Object.entries(update.$inc ?? {})) row[k] += v;',
    '        row.updatedAt = new Date(++clockMs);',
    '        return clone(row);',
    '    },',
    '};',
    'export const ManualDemoTrade = {',
    '    findOne: (filter) => makeOne(() => trades.find((t) => match(t, filter)) ?? null),',
    '    find: (filter) => makeQuery(() => trades.filter((t) => match(t, filter))),',
    '    create: async (docs) => {',
    '        const out = [];',
    '        for (const doc of docs) {',
    '            if (dupNextTradeCreate && doc.status === "rejected") {',
    '                const r = dupNextTradeCreate; dupNextTradeCreate = null;',
    '                trades.push({ ...r, _id: "trd-" + String(++idSeq).padStart(6, "0"), createdAt: new Date(++clockMs), updatedAt: new Date(clockMs) });',
    '                throw dupError();',
    '            }',
    '            if (trades.some((t) => t.userId === doc.userId && t.clientOrderId === doc.clientOrderId)) throw dupError();',
    '            const row = { ...doc, _id: "trd-" + String(++idSeq).padStart(6, "0"), createdAt: new Date(++clockMs), updatedAt: new Date(clockMs) };',
    '            trades.push(row); out.push(clone(row));',
    '        }',
    '        return out;',
    '    },',
    '};',
    'export function __reset() { accounts = []; trades = []; idSeq = 0; failVersionUpdates = 0; dupNextTradeCreate = null; clockMs = Date.now(); }',
    'export function __snapshot() { return { accounts: structuredClone(accounts), trades: structuredClone(trades), idSeq, clockMs }; }',
    'export function __restore(snap) { accounts = snap.accounts; trades = snap.trades; idSeq = snap.idSeq; clockMs = snap.clockMs; }',
    'export function __failNextVersionUpdates(n) { failVersionUpdates = n; }',
    'export function __counts() { return { accounts: accounts.length, trades: trades.length }; }',
    'export function __seedTrade(doc) { trades.push(doc); return doc; }',
    'export function __dupNextTradeCreate(row) { dupNextTradeCreate = row; }',
].join('\n');

// Types.ObjectId minimo: conserva el hex en __oid para que las
// comparaciones del stub (scalar/matchCond) trabajen sobre el string.
const MONGOOSE_TYPES_STUB = [
    'export const Types = {',
    '    ObjectId: class ObjectId {',
    '        constructor(id) { this.__oid = String(id); }',
    '        toString() { return this.__oid; }',
    '    },',
    '};',
].join('\n');

export async function load(url, context, nextLoad) {
    if (url === 'guard-stub:require-user') return { format: 'module', shortCircuit: true, source: REQUIRE_USER_STUB };
    if (url === 'guard-stub:mongoose') return { format: 'module', shortCircuit: true, source: MONGOOSE_STUB };
    if (url === 'guard-stub:manual-demo-model') return { format: 'module', shortCircuit: true, source: MODEL_STUB };
    if (url === 'guard-stub:request-locale') return { format: 'module', shortCircuit: true, source: "export async function requestLocale() { return 'es'; }" };
    if (url === 'guard-stub:mongoose-types') return { format: 'module', shortCircuit: true, source: MONGOOSE_TYPES_STUB };
    return nextLoad(url, context);
}
