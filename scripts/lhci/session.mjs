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

const base = process.env.LHCI_BASE_URL ?? 'http://127.0.0.1:3000';
const backend = process.env.LHCI_BACKEND_URL ?? 'http://127.0.0.1:8100';
const secret = process.env.RESEARCH_AUTH_SECRET;
if (!secret) throw new Error('RESEARCH_AUTH_SECRET es obligatorio');

const email = `lhci-${Date.now()}@example.com`;
const res = await fetch(`${base}/api/auth/sign-up/email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Origin: base },
    body: JSON.stringify({ email, password: `Lhci-${randomUUID()}`, name: 'Lighthouse CI' }),
});
if (!res.ok) throw new Error(`sign-up ${res.status}: ${(await res.text()).slice(0, 300)}`);
const { user } = await res.json();
const token = res.headers
    .getSetCookie()
    .map((c) => c.split(';')[0])
    .find((c) => c.startsWith('better-auth.session_token='));
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
    appendFileSync(process.env.GITHUB_ENV, `LHCI_COOKIE=${token}\n`);
    console.log('LHCI_COOKIE escrita en $GITHUB_ENV');
} else {
    console.log(`LHCI_COOKIE=${token}`);
}
