/**
 * better-auth (plugin twoFactor) responde 200 con `twoFactorRedirect: true` al
 * iniciar sesion con 2FA activo: no lanza. signInWithEmail debe convertirlo en
 * `twoFactorRequired`, no en exito (sin sesion, /inicio rebota a /sign-in).
 * Ejecución: node --experimental-strip-types --test scripts/sign-in-two-factor-redirect-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const src = readFileSync(join(root, 'lib/actions/auth.actions.ts'), 'utf8');

describe('signInWithEmail con 2FA', () => {
    it('trata twoFactorRedirect como paso 2FA pendiente, antes de devolver exito', () => {
        const fn = src.slice(src.indexOf('export const signInWithEmail'), src.indexOf('export const verifyTwoFactorTotp'));
        const redirectAt = fn.indexOf('twoFactorRedirect');
        const successAt = fn.indexOf('return { success: true, data: response }');
        assert.ok(redirectAt > -1, 'debe comprobar twoFactorRedirect');
        assert.ok(redirectAt < successAt, 'la comprobación va antes del éxito');
        assert.match(fn, /return \{ success: false, twoFactorRequired: true \}/);
    });
});
