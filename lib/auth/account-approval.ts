/**
 * Aprobación de cuentas nuevas: reglas puras (sin red ni base de datos).
 *
 * Modelo (tarea de Nico, 2026-10-31): el registro es abierto, pero cada
 * cuenta nueva nace `pending` y solo entra cuando Nico la aprueba desde el
 * correo de aviso (enlaces aprobar/rechazar firmados y de un solo uso).
 *
 * - El estado viaja en el documento `user` de Mongo como `accountStatus`
 *   (additionalField de better-auth con input:false + defaultValue; ver
 *   lib/better-auth/auth.ts). Las cuentas anteriores a la función no tienen
 *   el campo: se tratan como aprobadas (abuelas) y el script
 *   scripts/backfill-account-status.mjs les pone 'approved' explícito.
 * - Tokens HMAC sobre BETTER_AUTH_SECRET, mismo patrón que
 *   lib/auth/delete-reauth.ts. La firma cubre approvalId + acción + caducidad:
 *   no se puede cambiar approve por reject ni alargar el plazo.
 * - Un solo uso real: la decisión se consume de forma atómica sobre la
 *   colección account_approvals (ver app/api/admin/approvals/decide/route.ts);
 *   un enlace ya usado responde 410. La firma sola no podría garantizarlo.
 *
 * Módulo puro a propósito (sin alias `@/`, import con .ts explícita en los
 * tests): scripts/account-approval.test.ts lo ejecuta con node --test.
 */

import { createHmac, timingSafeEqual } from 'node:crypto';

export type AccountStatus = 'pending' | 'approved' | 'rejected';

export const ACCOUNT_PENDING_CODE = 'ACCOUNT_PENDING';
export const ACCOUNT_REJECTED_CODE = 'ACCOUNT_REJECTED';
export const ACCOUNT_PENDING_MESSAGE =
    'Tu cuenta está pendiente de aprobación. Te avisaremos por email cuando esté activa.';
export const ACCOUNT_REJECTED_MESSAGE = 'Tu solicitud de acceso no fue aprobada.';

export type ApprovalAction = 'approve' | 'reject';

/** Enlaces de decisión: 30 días por defecto (Nico puede tardar). */
export const APPROVAL_TOKEN_TTL_DEFAULT_MS = 30 * 24 * 60 * 60 * 1000;
/** Enlace del listado de respaldo incluido en cada aviso: 7 días. */
export const ADMIN_LIST_TOKEN_TTL_DEFAULT_MS = 7 * 24 * 60 * 60 * 1000;

type Env = Record<string, string | undefined>;

function parseTtlHours(raw: string | undefined, fallbackMs: number): number {
    const hours = Number(raw);
    if (!Number.isFinite(hours) || hours <= 0 || hours > 24 * 365) return fallbackMs;
    return Math.floor(hours * 60 * 60 * 1000);
}

export function approvalTokenTtlMs(env: Env): number {
    return parseTtlHours(env.APPROVAL_TOKEN_TTL_HOURS, APPROVAL_TOKEN_TTL_DEFAULT_MS);
}

export function adminListTokenTtlMs(env: Env): number {
    return parseTtlHours(env.ADMIN_LIST_TOKEN_TTL_HOURS, ADMIN_LIST_TOKEN_TTL_DEFAULT_MS);
}

/**
 * Cuentas anteriores a la función (sin el campo) cuentan como aprobadas:
 * el alta abierta es lo nuevo, no se puede bloquear a quien ya estaba dentro.
 */
export function normalizeAccountStatus(raw: unknown): AccountStatus | null {
    return raw === 'pending' || raw === 'approved' || raw === 'rejected' ? raw : null;
}

/** true si la cuenta puede usar la app. Campo ausente = abuelo aprobado. */
export function isAccountActive(rawStatus: unknown): boolean {
    const status = normalizeAccountStatus(rawStatus);
    return status === null || status === 'approved';
}

/**
 * E2E/desarrollo: SIGNUP_AUTO_APPROVE=true hace que las cuentas nuevas nazcan
 * aprobadas (playwright.config.ts lo fija en el servidor de user-flows).
 * IMPOSIBLE en producción: aunque la variable quede puesta por error en un
 * despliegue prod, aquí se ignora siempre.
 */
export function signupAutoApprove(env: Env): boolean {
    if (env.NODE_ENV === 'production') return false;
    return env.SIGNUP_AUTO_APPROVE === 'true' || env.SIGNUP_AUTO_APPROVE === '1';
}

function signature(payload: string, secret: string): string {
    return createHmac('sha256', secret).update(payload).digest('base64url');
}

function safeEqual(a: string, b: string): boolean {
    const ab = Buffer.from(a);
    const bb = Buffer.from(b);
    return ab.length === bb.length && timingSafeEqual(ab, bb);
}

/**
 * Token de decisión (aprobar/rechazar): `approvalId.action.expires.firma`.
 * La firma cubre los tres campos; approvalId es el ObjectId del registro de
 * account_approvals, que además da el carácter de un solo uso al consumirse.
 */
export function createDecisionToken(args: {
    approvalId: string;
    action: ApprovalAction;
    secret: string;
    nowMs?: number;
    ttlMs?: number;
}): string {
    const nowMs = args.nowMs ?? Date.now();
    const ttlMs = args.ttlMs ?? APPROVAL_TOKEN_TTL_DEFAULT_MS;
    const expires = Math.floor((nowMs + ttlMs) / 1000);
    const payload = `${args.approvalId}.${args.action}.${expires}`;
    return `${payload}.${signature(payload, args.secret)}`;
}

export type DecisionTokenPayload = { approvalId: string; action: ApprovalAction; expires: number };

export function verifyDecisionToken(
    token: string | null | undefined,
    secret: string | undefined,
    nowMs: number = Date.now(),
): DecisionTokenPayload | null {
    if (!token || !secret) return null;
    const parts = token.split('.');
    if (parts.length !== 4) return null;
    const [approvalId, action, rawExpires, provided] = parts;
    if (!approvalId || (action !== 'approve' && action !== 'reject') || !rawExpires || !provided) return null;
    const expires = Number(rawExpires);
    if (!Number.isInteger(expires) || expires * 1000 < nowMs) return null;
    const expected = signature(`${approvalId}.${action}.${rawExpires}`, secret);
    return safeEqual(provided, expected) ? { approvalId, action, expires } : null;
}

/**
 * Token del listado de respaldo (/api/admin/approvals): `list.expires.firma`.
 * Va en cada correo de aviso para que Nico vea todos los pendientes aunque
 * pierda un aviso concreto o el SMTP falle después.
 */
export function createAdminListToken(args: {
    secret: string;
    nowMs?: number;
    ttlMs?: number;
}): string {
    const nowMs = args.nowMs ?? Date.now();
    const ttlMs = args.ttlMs ?? ADMIN_LIST_TOKEN_TTL_DEFAULT_MS;
    const expires = Math.floor((nowMs + ttlMs) / 1000);
    const payload = `admin-list.${expires}`;
    return `${expires}.${signature(payload, args.secret)}`;
}

export function verifyAdminListToken(
    token: string | null | undefined,
    secret: string | undefined,
    nowMs: number = Date.now(),
): boolean {
    if (!token || !secret) return false;
    const [rawExpires, provided, ...rest] = token.split('.');
    if (!rawExpires || !provided || rest.length > 0) return false;
    const expires = Number(rawExpires);
    if (!Number.isInteger(expires) || expires * 1000 < nowMs) return false;
    return safeEqual(provided, signature(`admin-list.${rawExpires}`, secret));
}
