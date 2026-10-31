/**
 * Politica de alta: registro abierto con cuentas pendientes de aprobacion,
 * escotilla de cierre (ALLOW_PUBLIC_SIGNUP=false + SIGNUP_ALLOWLIST) y
 * arranque sin verificacion de email.
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
    it('produccion sin variables: alta ABIERTA (las cuentas nacen pendientes de aprobacion)', () => {
        const p = resolveSignupPolicy(PROD);
        assert.equal(p.publicOpen, true);
        assert.equal(p.signUpEnabled, true);
        assert.equal(isEmailAllowedToSignUp('qa@ejemplo.com', p), true);
    });

    it('ALLOW_PUBLIC_SIGNUP=false en produccion cierra el alta salvo invitados', () => {
        const p = resolveSignupPolicy({ ...PROD, ALLOW_PUBLIC_SIGNUP: 'false', SIGNUP_ALLOWLIST: 'qa@ejemplo.com' });
        assert.equal(p.publicOpen, false);
        assert.equal(p.signUpEnabled, true);
        assert.equal(isEmailAllowedToSignUp('  QA@Ejemplo.com ', p), true);
        assert.equal(isEmailAllowedToSignUp('intruso@ejemplo.com', p), false);
        assert.equal(isEmailAllowedToSignUp(undefined, p), false);
    });

    it('ALLOW_PUBLIC_SIGNUP=false sin lista de invitados: cerrada del todo y avisa', () => {
        const p = resolveSignupPolicy({ ...PROD, ALLOW_PUBLIC_SIGNUP: 'false' });
        assert.equal(p.publicOpen, false);
        assert.equal(p.signUpEnabled, false);
        assert.ok(p.warnings.some((w: string) => w.includes('ALLOW_PUBLIC_SIGNUP=false')));
    });

    it('REQUIRE_EMAIL_VERIFICATION=true sin envio se ignora con aviso, no bloquea el alta', () => {
        const p = resolveSignupPolicy({ ...PROD, REQUIRE_EMAIL_VERIFICATION: 'true' });
        assert.equal(p.requireEmailVerification, false);
        assert.ok(p.warnings.some((w: string) => w.includes('REQUIRE_EMAIL_VERIFICATION')));
    });

    it('los avisos nunca contienen los emails invitados', () => {
        const p = resolveSignupPolicy({ ...PROD, ALLOW_PUBLIC_SIGNUP: 'false', SIGNUP_ALLOWLIST: 'secreto@ejemplo.com', REQUIRE_EMAIL_VERIFICATION: 'true' });
        assert.ok(p.warnings.every((w: string) => !w.includes('secreto@')));
    });

    it('lista definida sin ningun email valido: avisa (y con el alta abierta no cierra nada)', () => {
        const p = resolveSignupPolicy({ ...PROD, SIGNUP_ALLOWLIST: 'no-es-email' });
        assert.equal(p.signUpEnabled, true);
        assert.ok(p.warnings.some((w: string) => w.includes('SIGNUP_ALLOWLIST')));
    });

    it('fuera de produccion el alta sigue abierta', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'development' });
        assert.equal(p.publicOpen, true);
        assert.equal(isEmailAllowedToSignUp('cualquiera@b.co', p), true);
    });
});

describe('signUpPageMode', () => {
    it('abierta por defecto; cerrada o invitacion solo con la escotilla de cierre', () => {
        assert.equal(signUpPageMode(resolveSignupPolicy(PROD), false), 'open');
        const closedInvited = resolveSignupPolicy({ ...PROD, ALLOW_PUBLIC_SIGNUP: 'false', SIGNUP_ALLOWLIST: 'qa@ejemplo.com' });
        assert.equal(signUpPageMode(closedInvited, false), 'closed');
        assert.equal(signUpPageMode(closedInvited, true), 'invite');
        assert.equal(signUpPageMode(resolveSignupPolicy({ ...PROD, ALLOW_PUBLIC_SIGNUP: 'false' }), false), 'closed');
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
