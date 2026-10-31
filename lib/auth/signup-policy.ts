/**
 * Politica de alta de cuentas: reglas puras (sin red ni base de datos).
 *
 * La comparten `lib/better-auth/auth.ts` (lo que el servidor acepta) y las
 * paginas de acceso (lo que se ensena), para que nunca digan cosas distintas.
 *
 * Modelo vigente (2026-10-31, decision de Nico): el registro esta ABIERTO a
 * cualquiera, pero cada cuenta nueva nace `pending` y no entra hasta que
 * Nico la aprueba desde el correo de aviso (ver lib/auth/account-approval.ts).
 * Abrir ya no abre el acceso: abre la solicitud.
 *
 * - `ALLOW_PUBLIC_SIGNUP=false` en produccion es la escotilla de cierre:
 *   vuelve al modelo anterior (alta cerrada salvo invitados de
 *   `SIGNUP_ALLOWLIST`, emails separados por comas).
 * - Fuera de produccion el alta siempre estuvo abierta; sigue igual.
 *
 * Verificacion de email: GerarAI aun no tiene envio de verificacion. Solo se
 * pide con REQUIRE_EMAIL_VERIFICATION=true y, mientras no exista el envio, se
 * ignora con un aviso en el log en lugar de tumbar el arranque o bloquear
 * el alta para siempre.
 */

type Env = Record<string, string | undefined>;

const EMAIL_RE = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]{2,}$/;

export type SignupPolicy = {
    /** Alta abierta a cualquiera (dev/test, o ALLOW_PUBLIC_SIGNUP=true en produccion). */
    publicOpen: boolean;
    /** Emails invitados, normalizados (minusculas, sin espacios). */
    allowlist: ReadonlySet<string>;
    /** better-auth acepta altas (abierta o con invitados): `disableSignUp = !signUpEnabled`. */
    signUpEnabled: boolean;
    /** Siempre false mientras no haya envio de verificacion (ver cabecera). */
    requireEmailVerification: boolean;
    /** Avisos para el log del servidor; nunca contienen emails. */
    warnings: string[];
};

/** Normaliza un email igual que el alta (recorta y pasa a minusculas). */
export function normalizeSignupEmail(email: unknown): string {
    return typeof email === 'string' ? email.trim().toLowerCase() : '';
}

/** Lee SIGNUP_ALLOWLIST: separada por comas, punto y coma o espacios; descarta lo que no es un email. */
export function parseSignupAllowlist(raw: string | undefined): Set<string> {
    const out = new Set<string>();
    for (const part of (raw ?? '').split(/[\s,;]+/)) {
        const email = normalizeSignupEmail(part);
        if (email && EMAIL_RE.test(email)) out.add(email);
    }
    return out;
}

export function resolveSignupPolicy(env: Env): SignupPolicy {
    const isProduction = env.NODE_ENV === 'production';
    // Alta abierta por defecto (las cuentas nacen pendientes de aprobación);
    // ALLOW_PUBLIC_SIGNUP=false en producción restaura el alta cerrada.
    const explicitlyClosed = isProduction && env.ALLOW_PUBLIC_SIGNUP === 'false';
    const publicOpen = !explicitlyClosed;
    const allowlist = parseSignupAllowlist(env.SIGNUP_ALLOWLIST);
    const signUpEnabled = publicOpen || allowlist.size > 0;
    const warnings: string[] = [];

    if (env.REQUIRE_EMAIL_VERIFICATION === 'true' && signUpEnabled) {
        warnings.push(
            'REQUIRE_EMAIL_VERIFICATION=true se ignora: no hay envío de email de verificación configurado ' +
            'y el alta quedaría bloqueada para siempre. Las cuentas nuevas se crean sin verificar el email.',
        );
    }
    if (explicitlyClosed && allowlist.size === 0) {
        warnings.push(
            'Registro cerrado en producción (ALLOW_PUBLIC_SIGNUP=false) y SIGNUP_ALLOWLIST vacía: ' +
            'nadie puede crear una cuenta. Es la escotilla de cierre; quita la variable para volver al alta abierta con aprobación.',
        );
    }
    const rawAllowlist = (env.SIGNUP_ALLOWLIST ?? '').trim();
    if (rawAllowlist && allowlist.size === 0) {
        warnings.push('SIGNUP_ALLOWLIST está definida pero no contiene ningún email válido; se ignora.');
    }

    return { publicOpen, allowlist, signUpEnabled, requireEmailVerification: false, warnings };
}

/** Si este email puede crear cuenta con la politica dada. */
export function isEmailAllowedToSignUp(email: unknown, policy: SignupPolicy): boolean {
    if (policy.publicOpen) return true;
    const normalized = normalizeSignupEmail(email);
    return normalized !== '' && policy.allowlist.has(normalized);
}

/**
 * Que ensena /sign-up:
 * - `open`: formulario de alta normal;
 * - `invite`: formulario de alta solo para invitados (se llega con ?invitacion);
 * - `closed`: solicitud de acceso (y, si hay invitados, un enlace al modo invitacion).
 */
export type SignUpPageMode = 'open' | 'invite' | 'closed';

export function signUpPageMode(policy: SignupPolicy, wantsInvitation: boolean): SignUpPageMode {
    if (policy.publicOpen) return 'open';
    if (policy.allowlist.size > 0 && wantsInvitation) return 'invite';
    return 'closed';
}

/** Codigo y texto del rechazo de un email no invitado (better-auth -> lib/auth/endpoint.ts). */
export const SIGNUP_NOT_INVITED_CODE = 'SIGNUP_NOT_INVITED';
export const SIGNUP_NOT_INVITED_MESSAGE =
    'Este email no está invitado. Pide acceso desde esta misma página y te avisamos.';
