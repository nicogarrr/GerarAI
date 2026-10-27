/**
 * Politica de alta: lista de invitados (SIGNUP_ALLOWLIST) y arranque sin
 * verificacion de email cuando el registro se abre.
 * Ejecucion: node --experimental-strip-types --test scripts/signup-policy.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    isEmailAllowedToSignUp,
    parseSignupAllowlist,
    resolveSignupPolicy,
    signUpPageMode,
    // @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
} from '../lib/auth/signup-policy.ts';

const PROD = { NODE_ENV: 'production' };

describe('parseSignupAllowlist', () => {
    it('separa por comas, punto y coma y espacios; normaliza y descarta basura', () => {
        const set = parseSignupAllowlist(' QA@Ejemplo.com, otro@b.co;tercero@c.io  no-es-email ,, ');
        assert.deepEqual([...set].sort(), ['otro@b.co', 'qa@ejemplo.com', 'tercero@c.io']);
    });
    it('vacia o ausente da conjunto vacio', () => {
        assert.equal(parseSignupAllowlist(undefined).size, 0);
        assert.equal(parseSignupAllowlist('   ').size, 0);
    });
});

describe('resolveSignupPolicy', () => {
    it('produccion sin variables: alta cerrada, nadie entra', () => {
        const p = resolveSignupPolicy(PROD);
        assert.equal(p.publicOpen, false);
        assert.equal(p.signUpEnabled, false);
        assert.equal(isEmailAllowedToSignUp('qa@ejemplo.com', p), false);
    });

    it('produccion con lista de invitados: solo esos emails, sin abrir el registro', () => {
        const p = resolveSignupPolicy({ ...PROD, SIGNUP_ALLOWLIST: 'qa@ejemplo.com' });
        assert.equal(p.publicOpen, false);
        assert.equal(p.signUpEnabled, true);
        assert.equal(isEmailAllowedToSignUp('  QA@Ejemplo.com ', p), true);
        assert.equal(isEmailAllowedToSignUp('intruso@ejemplo.com', p), false);
        assert.equal(isEmailAllowedToSignUp(undefined, p), false);
    });

    it('ALLOW_PUBLIC_SIGNUP=true en produccion ya no exige verificacion (antes la app no arrancaba)', () => {
        const p = resolveSignupPolicy({ ...PROD, ALLOW_PUBLIC_SIGNUP: 'true' });
        assert.equal(p.publicOpen, true);
        assert.equal(p.requireEmailVerification, false);
        assert.ok(p.warnings.some((w: string) => w.includes('ALLOW_PUBLIC_SIGNUP')));
    });

    it('REQUIRE_EMAIL_VERIFICATION=true sin envio se ignora con aviso, no bloquea el alta', () => {
        const p = resolveSignupPolicy({ ...PROD, SIGNUP_ALLOWLIST: 'qa@ejemplo.com', REQUIRE_EMAIL_VERIFICATION: 'true' });
        assert.equal(p.requireEmailVerification, false);
        assert.ok(p.warnings.some((w: string) => w.includes('REQUIRE_EMAIL_VERIFICATION')));
    });

    it('los avisos nunca contienen los emails invitados', () => {
        const p = resolveSignupPolicy({ ...PROD, ALLOW_PUBLIC_SIGNUP: 'true', SIGNUP_ALLOWLIST: 'secreto@ejemplo.com', REQUIRE_EMAIL_VERIFICATION: 'true' });
        assert.ok(p.warnings.every((w: string) => !w.includes('secreto@')));
    });

    it('lista definida sin ningun email valido: avisa y sigue cerrada', () => {
        const p = resolveSignupPolicy({ ...PROD, SIGNUP_ALLOWLIST: 'no-es-email' });
        assert.equal(p.signUpEnabled, false);
        assert.ok(p.warnings.some((w: string) => w.includes('SIGNUP_ALLOWLIST')));
    });

    it('fuera de produccion el alta sigue abierta', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'development' });
        assert.equal(p.publicOpen, true);
        assert.equal(isEmailAllowedToSignUp('cualquiera@b.co', p), true);
    });
});

describe('signUpPageMode', () => {
    it('cerrada, invitacion u abierta segun la politica y ?invitacion', () => {
        assert.equal(signUpPageMode(resolveSignupPolicy(PROD), true), 'closed');
        const invited = resolveSignupPolicy({ ...PROD, SIGNUP_ALLOWLIST: 'qa@ejemplo.com' });
        assert.equal(signUpPageMode(invited, false), 'closed');
        assert.equal(signUpPageMode(invited, true), 'invite');
        assert.equal(signUpPageMode(resolveSignupPolicy({ ...PROD, ALLOW_PUBLIC_SIGNUP: 'true' }), false), 'open');
    });
});

describe('auth.ts usa la politica compartida', () => {
    const src = readFileSync('lib/better-auth/auth.ts', 'utf8');
    it('no vuelve a exigir verificacion por el mero hecho de estar en produccion ni a lanzar al arrancar', () => {
        assert.doesNotMatch(src, /NODE_ENV === 'production' \|\| process\.env\.REQUIRE_EMAIL_VERIFICATION/);
        assert.doesNotMatch(src, /throw new Error\(\s*'Registro abierto con verificación/);
    });
    it('el alta se filtra por la lista de invitados en el servidor', () => {
        assert.match(src, /resolveSignupPolicy\(process\.env\)/);
        assert.match(src, /isEmailAllowedToSignUp\(/);
        assert.match(src, /'\/sign-up\/email'/);
    });
});
