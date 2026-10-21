/**
 * Login con 2FA activo. Dos cosas deben cumplirse a la vez:
 * 1) better-auth (plugin twoFactor) NO lanza: responde 200 con
 *    `twoFactorRedirect: true`. signInWithEmail debe devolverlo como
 *    `twoFactorRequired`, no como exito.
 * 2) nextCookies() va el ULTIMO en `plugins`; si no, cookies().set de Next recibe
 *    el session_token previo al 2FA y no la cookie two_factor.
 * El test 2 ejecuta better-auth real (memoria) con next/headers simulado y
 * comprueba las cookies que Next recibiria, con el orden de auth.ts.
 * Ejecución: node --experimental-strip-types --experimental-test-module-mocks --test scripts/sign-in-two-factor-redirect-guard.test.ts
 */
import { describe, it, mock } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHmac } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const actions = readFileSync(join(root, 'lib/actions/auth.actions.ts'), 'utf8');
const authSrc = readFileSync(join(root, 'lib/better-auth/auth.ts'), 'utf8');

describe('signInWithEmail con 2FA', () => {
    it('trata twoFactorRedirect como paso 2FA pendiente, antes de devolver exito', () => {
        const fn = actions.slice(actions.indexOf('export const signInWithEmail'), actions.indexOf('export const verifyTwoFactorTotp'));
        const redirectAt = fn.indexOf('twoFactorRedirect');
        const successAt = fn.indexOf('return { success: true, data: response }');
        assert.ok(redirectAt > -1, 'debe comprobar twoFactorRedirect');
        assert.ok(redirectAt < successAt, 'la comprobación va antes del éxito');
        assert.match(fn, /return \{ success: false, twoFactorRequired: true \}/);
    });
});

describe('orden de plugins de better-auth', () => {
    it('auth.ts deja nextCookies() el último', () => {
        const block = authSrc.slice(authSrc.indexOf('plugins: ['));
        const list = block.slice(0, block.indexOf('],'));
        assert.ok(list.indexOf('twoFactor(') > -1 && list.indexOf('nextCookies()') > list.indexOf('twoFactor('));
    });

    it('con ese orden, Next recibe two_factor y no un session_token vivo', async () => {
        const sets: Array<[string, string]> = [];
        mock.module('next/headers.js', {
            namedExports: {
                headers: async () => new Headers(),
                cookies: async () => ({ set: (n: string, v: string) => sets.push([n, v]), get: () => undefined }),
            },
        });
        const { betterAuth } = await import('better-auth');
        const { memoryAdapter } = await import('better-auth/adapters/memory');
        const { twoFactor } = await import('better-auth/plugins');
        const { nextCookies } = await import('better-auth/next-js');
        const db = { user: [], session: [], account: [], verification: [], twoFactor: [] };
        const auth = betterAuth({
            database: memoryAdapter(db),
            secret: 'x'.repeat(40),
            baseURL: 'http://localhost:3000',
            emailAndPassword: { enabled: true },
            plugins: [twoFactor({ issuer: 't' }), nextCookies()], // mismo orden que lib/better-auth/auth.ts
        });
        const totp = (secret: string) => {
            const b32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
            let bits = '';
            for (const c of secret.toUpperCase()) bits += b32.indexOf(c).toString(2).padStart(5, '0');
            const key = Buffer.from((bits.match(/.{8}/g) as string[]).map((x) => parseInt(x, 2)));
            const ctr = Buffer.alloc(8);
            ctr.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
            const h = createHmac('sha1', key).update(ctr).digest();
            const o = h[19] & 15;
            return String((h.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, '0');
        };
        await auth.api.signUpEmail({ body: { email: 'a@b.co', password: 'password123', name: 'A' } });
        const si = await auth.api.signInEmail({ body: { email: 'a@b.co', password: 'password123' }, asResponse: true });
        const cookie = si.headers.getSetCookie().map((c) => c.split(';')[0]).join('; ');
        const en = await auth.api.enableTwoFactor({ body: { password: 'password123' }, headers: new Headers({ cookie }) });
        // enableTwoFactor devuelve una union (TOTP u OTP): sin totpURI no hay secreto que probar.
        assert.ok('totpURI' in en && typeof en.totpURI === 'string', 'enableTwoFactor debe devolver totpURI');
        const secret = new URL(en.totpURI).searchParams.get('secret');
        assert.ok(secret, 'totpURI debe llevar secret');
        await auth.api.verifyTOTP({
            body: { code: totp(secret) },
            headers: new Headers({ cookie }),
        });
        sets.length = 0;
        const res = (await auth.api.signInEmail({ body: { email: 'a@b.co', password: 'password123' } })) as { twoFactorRedirect?: boolean };
        assert.equal(res.twoFactorRedirect, true);
        const names = sets.map(([n]) => n);
        assert.ok(names.includes('better-auth.two_factor'), `falta two_factor: ${names.join(',')}`);
        const session = sets.find(([n]) => n === 'better-auth.session_token');
        assert.ok(!session || session[1] === '', 'el session_token previo al 2FA no debe llegar a Next con valor');
    });
});
