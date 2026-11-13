import { describe, expect, it } from 'vitest';

import {
    isEmailAllowedToSignUp,
    normalizeSignupEmail,
    parseSignupAllowlist,
    resolveSignupPolicy,
    signUpPageMode,
    SIGNUP_NOT_INVITED_CODE,
    SIGNUP_NOT_INVITED_MESSAGE,
} from '@/lib/auth/signup-policy';

/**
 * Política de alta de cuentas: reglas puras compartidas por better-auth y las
 * páginas de acceso. Antes no había tests: el cambio de «cerrada por defecto»
 * a «abierta con aprobación» (31-oct-2026) se hizo sin red de seguridad.
 */

describe('normalizeSignupEmail', () => {
    it('recorta, pasa a minúsculas y descarta no-texto', () => {
        expect(normalizeSignupEmail('  Ana@Example.COM  ')).toBe('ana@example.com');
        expect(normalizeSignupEmail('')).toBe('');
        expect(normalizeSignupEmail(null)).toBe('');
        expect(normalizeSignupEmail(42)).toBe('');
    });
});

describe('parseSignupAllowlist', () => {
    it('acepta comas, punto y coma o espacios', () => {
        const set = parseSignupAllowlist('a@b.es, c@d.es;e@f.es g@h.es');
        expect(set).toEqual(new Set(['a@b.es', 'c@d.es', 'e@f.es', 'g@h.es']));
    });

    it('normaliza mayúsculas y espacios', () => {
        const set = parseSignupAllowlist('  ANA@B.ES ,  C@D.ES  ');
        expect(set).toEqual(new Set(['ana@b.es', 'c@d.es']));
    });

    it('descarta entradas que no son email', () => {
        const set = parseSignupAllowlist('no-es-email, a@b.es, tambiénmal');
        expect(set).toEqual(new Set(['a@b.es']));
    });

    it('devuelve conjunto vacío sin variable', () => {
        expect(parseSignupAllowlist(undefined)).toEqual(new Set());
        expect(parseSignupAllowlist('')).toEqual(new Set());
        expect(parseSignupAllowlist('   ')).toEqual(new Set());
    });
});

describe('resolveSignupPolicy', () => {
    const env = (over: Record<string, string | undefined> = {}) => ({
        NODE_ENV: 'production',
        ALLOW_PUBLIC_SIGNUP: undefined,
        SIGNUP_ALLOWLIST: undefined,
        REQUIRE_EMAIL_VERIFICATION: undefined,
        ...over,
    });

    it('producción sin ALLOW_PUBLIC_SIGNUP: alta abierta (cuentas pendientes de aprobación)', () => {
        const p = resolveSignupPolicy(env());
        expect(p.publicOpen).toBe(true);
        expect(p.signUpEnabled).toBe(true);
        expect(p.requireEmailVerification).toBe(false);
    });

    it('ALLOW_PUBLIC_SIGNUP=false en producción: alta cerrada salvo allowlist', () => {
        const p = resolveSignupPolicy(env({ ALLOW_PUBLIC_SIGNUP: 'false', SIGNUP_ALLOWLIST: 'a@b.es' }));
        expect(p.publicOpen).toBe(false);
        expect(p.signUpEnabled).toBe(true);
        expect(p.allowlist).toEqual(new Set(['a@b.es']));
    });

    it('ALLOW_PUBLIC_SIGNUP=false sin allowlist: nadie entra, con aviso', () => {
        const p = resolveSignupPolicy(env({ ALLOW_PUBLIC_SIGNUP: 'false' }));
        expect(p.publicOpen).toBe(false);
        expect(p.signUpEnabled).toBe(false);
        expect(p.warnings.some((w) => w.includes('nadie puede crear'))).toBe(true);
    });

    it('fuera de producción el alta siempre está abierta', () => {
        const p = resolveSignupPolicy(env({ NODE_ENV: 'development' }));
        expect(p.publicOpen).toBe(true);
    });

    it('REQUIRE_EMAIL_VERIFICATION=true se ignora con aviso, no bloquea', () => {
        const p = resolveSignupPolicy(env({ REQUIRE_EMAIL_VERIFICATION: 'true' }));
        expect(p.requireEmailVerification).toBe(false);
        expect(p.warnings.some((w) => w.includes('REQUIRE_EMAIL_VERIFICATION'))).toBe(true);
    });

    it('allowlist con solo entradas inválidas: aviso y conjunto vacío', () => {
        const p = resolveSignupPolicy(env({ ALLOW_PUBLIC_SIGNUP: 'false', SIGNUP_ALLOWLIST: 'no-es-email' }));
        expect(p.allowlist.size).toBe(0);
        expect(p.warnings.some((w) => w.includes('no contiene ningún email válido'))).toBe(true);
    });
});

describe('isEmailAllowedToSignUp', () => {
    it('alta abierta: cualquier email entra', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'production' });
        expect(isEmailAllowedToSignUp('cualquiera@ejemplo.es', p)).toBe(true);
    });

    it('alta cerrada: solo allowlist, normalizado', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'production', ALLOW_PUBLIC_SIGNUP: 'false', SIGNUP_ALLOWLIST: 'ana@b.es' });
        expect(isEmailAllowedToSignUp('ANA@B.ES', p)).toBe(true);
        expect(isEmailAllowedToSignUp('otro@b.es', p)).toBe(false);
    });

    it('alta cerrada sin allowlist: nadie entra', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'production', ALLOW_PUBLIC_SIGNUP: 'false' });
        expect(isEmailAllowedToSignUp('ana@b.es', p)).toBe(false);
    });
});

describe('signUpPageMode', () => {
    it('alta abierta: siempre open', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'production' });
        expect(signUpPageMode(p, false)).toBe('open');
        expect(signUpPageMode(p, true)).toBe('open');
    });

    it('alta cerrada con allowlist y ?invitacion: invite', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'production', ALLOW_PUBLIC_SIGNUP: 'false', SIGNUP_ALLOWLIST: 'a@b.es' });
        expect(signUpPageMode(p, true)).toBe('invite');
    });

    it('alta cerrada con allowlist sin ?invitacion: closed', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'production', ALLOW_PUBLIC_SIGNUP: 'false', SIGNUP_ALLOWLIST: 'a@b.es' });
        expect(signUpPageMode(p, false)).toBe('closed');
    });

    it('alta cerrada sin allowlist: siempre closed', () => {
        const p = resolveSignupPolicy({ NODE_ENV: 'production', ALLOW_PUBLIC_SIGNUP: 'false' });
        expect(signUpPageMode(p, false)).toBe('closed');
        expect(signUpPageMode(p, true)).toBe('closed');
    });
});

describe('mensaje de rechazo', () => {
    it('código y texto estable para el frontend', () => {
        expect(SIGNUP_NOT_INVITED_CODE).toBe('SIGNUP_NOT_INVITED');
        expect(SIGNUP_NOT_INVITED_MESSAGE).toContain('no está invitado');
    });
});
