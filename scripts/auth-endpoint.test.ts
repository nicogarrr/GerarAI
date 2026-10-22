import assert from 'node:assert/strict';
import { test } from 'node:test';
import { register } from 'node:module';
import { betterAuth } from 'better-auth';
import { memoryAdapter } from 'better-auth/adapters/memory';
import { twoFactor } from 'better-auth/plugins';
import { createHmac } from 'node:crypto';
register('./auth-endpoint.loader.mjs', import.meta.url);
// @ts-expect-error TS5097: node strip-types needs the source extension.
const { callAuthEndpoint } = await import('../lib/auth/endpoint.ts');
const state = globalThis as typeof globalThis & { __endpointAuth: unknown; __endpointHeaders: Headers; __endpointCookies: Array<[string, string, { httpOnly?: boolean }]> };
const credentials = { email: 'synthetic@example.com', password: 'synthetic-password-123', name: 'Test' };
function configure(rateLimit: Parameters<typeof betterAuth>[0]['rateLimit']) {
    const auth = betterAuth({ database: memoryAdapter({ user: [], session: [], account: [], verification: [], twoFactor: [] }), secret: 'synthetic-only-test-'.repeat(3), baseURL: 'http://localhost:3000', emailAndPassword: { enabled: true }, plugins: [twoFactor({ issuer: 'test' })], rateLimit });
    state.__endpointAuth = auth;
    state.__endpointHeaders = new Headers({ origin: 'http://localhost:3000', 'x-forwarded-for': '203.0.113.71' });
    state.__endpointCookies = [];
    return auth;
}
function cookieHeader() { return state.__endpointCookies.map(([n, v]) => `${n}=${encodeURIComponent(v)}`).join('; '); }
function totp(secret: string) {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = '';
    for (const c of secret) bits += alphabet.indexOf(c).toString(2).padStart(5, '0');
    const key = Buffer.from((bits.match(/.{8}/g) ?? []).map(x => parseInt(x, 2)));
    const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
    const digest = createHmac('sha1', key).update(counter).digest();
    return String((digest.readUInt32BE(digest[19] & 15) & 0x7fffffff) % 1e6).padStart(6, '0');
}

test('real helper/router preserves HttpOnly session, pending 2FA and cookie deletions without returning token', async () => {
    const auth = configure({ enabled: false });
    assert.deepEqual(await callAuthEndpoint('/sign-up/email', credentials), { twoFactorRedirect: false });
    assert.ok(state.__endpointCookies.find(([n, v, o]) => n === 'better-auth.session_token' && v && o.httpOnly));
    const cookie = cookieHeader();
    const enabled = await auth.api.enableTwoFactor({ body: { password: credentials.password }, headers: new Headers({ cookie }) });
    assert.ok('totpURI' in enabled && enabled.totpURI);
    const secret = new URL(enabled.totpURI).searchParams.get('secret'); assert.ok(secret);
    await auth.api.verifyTOTP({ body: { code: totp(secret) }, headers: new Headers({ cookie }) });
    state.__endpointCookies = [];
    assert.deepEqual(await callAuthEndpoint('/sign-in/email', credentials), { twoFactorRedirect: true });
    assert.ok(state.__endpointCookies.find(([n, v]) => n === 'better-auth.two_factor' && v));
    assert.ok(!state.__endpointCookies.find(([n, v]) => n === 'better-auth.session_token' && v));
    state.__endpointHeaders.set('cookie', cookieHeader()); state.__endpointCookies = [];
    await callAuthEndpoint('/two-factor/verify-totp', { code: totp(secret) });
    assert.ok(state.__endpointCookies.find(([n, v, o]) => n === 'better-auth.session_token' && v && o.httpOnly));
    assert.ok(state.__endpointCookies.find(([n, v]) => n === 'better-auth.two_factor' && v === ''));
});

test('official concurrent rate limit, 401/429 status, retry TTL and IP chains stay unchanged', async () => {
    configure({ enabled: true, customRules: { '/sign-in/email': { window: 1, max: 2 } } });
    state.__endpointHeaders.set('x-forwarded-for', '203.0.113.72');
    const results = await Promise.allSettled(Array.from({ length: 8 }, () => callAuthEndpoint('/sign-in/email', credentials)));
    const statuses = results.map(r => r.status === 'rejected' ? r.reason.statusCode : 200);
    assert.equal(statuses.filter(x => x === 401).length, 2); assert.equal(statuses.filter(x => x === 429).length, 6);
    await new Promise(r => setTimeout(r, 1100));
    await assert.rejects(() => callAuthEndpoint('/sign-in/email', credentials), { statusCode: 401 });
    // Invalid multi-hop XFF is NOT simplified to attacker-controlled first IP.
    // The existing official resolver chooses its fallback bucket; no new trust.
    state.__endpointHeaders.set('x-forwarded-for', '203.0.113.1, 203.0.113.2');
    await assert.rejects(() => callAuthEndpoint('/sign-in/email', credentials), { statusCode: 401 });
    state.__endpointHeaders.set('x-forwarded-for', '203.0.113.3, 203.0.113.2');
    await assert.rejects(() => callAuthEndpoint('/sign-in/email', credentials), { statusCode: 401 });
    state.__endpointHeaders.set('x-forwarded-for', '203.0.113.4, 203.0.113.2');
    await assert.rejects(() => callAuthEndpoint('/sign-in/email', credentials), { statusCode: 429 });
});

test('untrusted Origin is rejected and inbound Host cannot set the auth target', async () => {
    configure({ enabled: false });
    state.__endpointHeaders.set('origin', 'https://untrusted.invalid');
    state.__endpointHeaders.set('host', 'untrusted.invalid');
    state.__endpointHeaders.set('x-forwarded-host', 'untrusted.invalid');
    await assert.rejects(() => callAuthEndpoint('/sign-in/email', credentials), { statusCode: 403 });
    assert.deepEqual(state.__endpointCookies, []);
    state.__endpointHeaders.set('origin', 'http://localhost:3000');
    await assert.rejects(() => callAuthEndpoint('/sign-in/email', credentials), { statusCode: 401 });
    // The Host values above cannot redirect the helper to an external host.
    state.__endpointHeaders.delete('origin');
    state.__endpointHeaders.set('sec-fetch-site', 'cross-site');
    state.__endpointHeaders.set('sec-fetch-mode', 'navigate');
    state.__endpointHeaders.set('sec-fetch-dest', 'document');
    await assert.rejects(() => callAuthEndpoint('/sign-in/email', credentials), { statusCode: 403 });
});

test('rate-limit store failure fails closed with sanitized 503 and no cookies', async () => {
    configure({ enabled: true, customStorage: { consume: async () => { throw new Error('synthetic-internal-secret'); } } });
    await assert.rejects(() => callAuthEndpoint('/sign-in/email', credentials), (error: unknown) => {
        const e = error as { statusCode: number; message: string }; assert.equal(e.statusCode, 503); assert.ok(!e.message.includes('synthetic-internal-secret')); return true;
    });
    assert.deepEqual(state.__endpointCookies, []);
});
