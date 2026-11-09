#!/usr/bin/env node
/**
 * Sesión real para Lighthouse CI (.github/workflows/a11y-perf.yml).
 *
 * En producción (NODE_ENV=production) el bypass E2E está apagado, así que las
 * pantallas firmadas necesitan una cookie de better-auth de verdad. Este script
 * da de alta un usuario efímero contra el `next start` del job (Mongo efímero,
 * ALLOW_PUBLIC_SIGNUP=true, sin verificación de email), siembra unos pocos datos
 * en el backend APP_ENV=test con la misma firma HMAC que usa la app
 * (lib/auth/research-identity.ts: tenant = user.id) y escribe la cookie en
 * $GITHUB_ENV como LHCI_COOKIE (o la imprime si no hay $GITHUB_ENV).
 *
 * Uso: node scripts/lhci/session.mjs
 *   LHCI_BASE_URL       (http://127.0.0.1:3000)
 *   LHCI_BACKEND_URL    (http://127.0.0.1:8100)
 *   RESEARCH_AUTH_SECRET
 */
import { createHash, createHmac, randomUUID } from 'node:crypto';
import { appendFileSync } from 'node:fs';
import mongoose from 'mongoose';

const base = process.env.LHCI_BASE_URL ?? 'http://127.0.0.1:3000';
const backend = process.env.LHCI_BACKEND_URL ?? 'http://127.0.0.1:8100';
const secret = process.env.RESEARCH_AUTH_SECRET;
if (!secret) throw new Error('RESEARCH_AUTH_SECRET es obligatorio');

const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost', '::1', '[::1]']);

/** La autoaprobación de CI solo vale contra servicios locales efímeros. */
function assertLocal(raw, name, { protocol, dbName } = {}) {
    let u;
    try {
        u = new URL(raw);
    } catch {
        throw new Error(`autoaprobación CI denegada: ${name} no es una URL válida`);
    }
    if (protocol && u.protocol !== protocol) {
        throw new Error(`autoaprobación CI denegada: ${name} no usa ${protocol}//`);
    }
    if (!LOCAL_HOSTS.has(u.hostname)) {
        throw new Error(`autoaprobación CI denegada: ${name} no apunta a un host local`);
    }
    if (dbName && u.pathname.replace(/^\//, '').split(/[?/]/)[0] !== dbName) {
        throw new Error(`autoaprobación CI denegada: ${name} no usa la base de datos efímera ${dbName}`);
    }
}

// Guardas de arranque: el script da de alta una cuenta y la autoaprueba en
// Mongo, así que solo corre en CI y contra los servicios locales efímeros
// del job. Todo se valida ANTES de cualquier llamada remota.
if (process.env.CI !== 'true') {
    throw new Error('solo corre en CI (CI=true); la siembra autoaprueba cuentas en Mongo');
}
assertLocal(base, 'LHCI_BASE_URL', { protocol: 'http:' });
assertLocal(backend, 'LHCI_BACKEND_URL', { protocol: 'http:' });
const mongoUri = process.env.MONGODB_URI;
if (!mongoUri) throw new Error('MONGODB_URI es obligatorio (autoaprobación de la cuenta efímera de CI)');
assertLocal(mongoUri, 'MONGODB_URI', { protocol: 'mongodb:', dbName: 'cavaai_lhci' });

const email = `lhci-${Date.now()}@example.com`;
const password = `Lhci-${randomUUID()}`;
const res = await fetch(`${base}/api/auth/sign-up/email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Origin: base },
    body: JSON.stringify({ email, password, name: 'Lighthouse CI' }),
});
// Errores sin cuerpo remoto: solo fase y status (un 500 podría traer datos sensibles).
if (!res.ok) throw new Error(`sign-up falló: HTTP ${res.status}`);
const { user } = await res.json();
const sessionCookie = (r) =>
    r.headers
        .getSetCookie()
        .map((c) => c.split(';')[0])
        .find((c) => c.startsWith('better-auth.session_token='));
let token = sessionCookie(res);
if (!token) {
    // Alta abierta con aprobación (31-oct-2026): la cuenta nace `pending` y
    // sin sesión (autoSignIn=false), y en producción SIGNUP_AUTO_APPROVE no
    // aplica a propósito. En CI nos autoaprobamos directamente en el Mongo
    // efímero del job y entramos por /sign-in/email, el mismo camino que
    // recorre cualquier cuenta aprobada.
    await mongoose.connect(mongoUri);
    try {
        const r = await mongoose.connection.db
            .collection('user')
            .updateOne({ email }, { $set: { accountStatus: 'approved' } });
        if (r.matchedCount !== 1) throw new Error(`autoaprobación CI: usuario ${email} no encontrado en Mongo`);
    } finally {
        await mongoose.disconnect();
    }
    const login = await fetch(`${base}/api/auth/sign-in/email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: base },
        body: JSON.stringify({ email, password }),
    });
    if (!login.ok) throw new Error(`sign-in CI falló: HTTP ${login.status}`);
    token = sessionCookie(login);
}
if (!user?.id || !token) throw new Error('sign-up sin usuario o sin cookie de sesión');

async function signed(method, path, body) {
    const raw = body === undefined ? Buffer.alloc(0) : Buffer.from(JSON.stringify(body));
    const ts = String(Math.floor(Date.now() / 1000));
    const nonce = randomUUID().replace(/-/g, '');
    const bodyHash = createHash('sha256').update(raw).digest('hex');
    const sig = createHmac('sha256', secret)
        .update(`${user.id}:${user.id}:${ts}:${nonce}:${method}:${path}:${bodyHash}`)
        .digest('hex');
    const r = await fetch(`${backend}${path}`, {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-CavaAI-Tenant': user.id,
            'X-CavaAI-User': user.id,
            'X-CavaAI-Timestamp': ts,
            'X-CavaAI-Nonce': nonce,
            'X-CavaAI-Method': method,
            'X-CavaAI-Path': path,
            'X-CavaAI-Body-Hash': bodyHash,
            'X-CavaAI-Signature': sig,
        },
        body: body === undefined ? undefined : raw,
    });
    return r.status;
}

// Datos mínimos para que watchlist, ficha, cartera e impuestos no midan un
// estado vacío. Un fallo de siembra no tumba el job: se mide lo que haya.
const companies = [
    { ticker: 'AAPL', name: 'Apple Inc', exchange: 'NASDAQ', currency: 'USD' },
    { ticker: 'MSFT', name: 'Microsoft Corp', exchange: 'NASDAQ', currency: 'USD' },
    { ticker: 'VOD.L', name: 'Vodafone Group', exchange: 'LSE', currency: 'GBp' },
    { ticker: 'MC.PA', name: 'LVMH', exchange: 'EPA', currency: 'EUR' },
];
const statuses = [];
for (const c of companies) statuses.push(await signed('POST', '/api/companies/ensure', c));
for (const c of companies) statuses.push(await signed('POST', '/api/watchlist', { symbol: c.ticker }));
for (const t of [
    { ticker: 'AAPL', action: 'buy', quantity: 10, price: 150, trade_date: '2025-03-10', currency: 'USD' },
    { ticker: 'MSFT', action: 'buy', quantity: 5, price: 350, trade_date: '2025-02-03', currency: 'USD' },
    { ticker: 'MC.PA', action: 'buy', quantity: 3, price: 600, trade_date: '2025-05-05', currency: 'EUR' },
]) {
    statuses.push(await signed('POST', '/api/portfolio/transactions', { ...t, fees: 1 }));
}
console.log(`usuario ${user.id}; siembra: ${statuses.join(' ')}`);

if (process.env.GITHUB_ENV) {
    // Enmascara la cookie antes de escribirla: no debe aparecer en los logs.
    console.log(`::add-mask::${token}`);
    appendFileSync(process.env.GITHUB_ENV, `LHCI_COOKIE=${token}\n`);
    console.log('LHCI_COOKIE escrita en $GITHUB_ENV');
} else {
    // Fuera de Actions la cookie no se imprime: quien la necesite que lea
    // el paso equivalente en su entorno o use GITHUB_ENV.
    console.log('LHCI_COOKIE obtenida (no se imprime fuera de CI)');
}
