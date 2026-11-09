// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { hmacSignature, safeEqual } from './hmac.ts';

export const DELETE_REAUTH_HEADER = 'x-cavaai-delete-reauth';
export const DELETE_REAUTH_TTL_MS = 120_000;

export function createDeleteReauthToken(
    userId: string,
    secret: string | undefined,
    nowMs: number = Date.now(),
): string {
    if (!secret) {
        throw new Error('BETTER_AUTH_SECRET is required for account reauthentication');
    }
    const expires = Math.floor((nowMs + DELETE_REAUTH_TTL_MS) / 1000);
    return `${expires}.${hmacSignature(`${userId}.${expires}`, secret)}`;
}

export function verifyDeleteReauthToken(
    token: string | null | undefined,
    userId: string,
    secret: string | undefined,
    nowMs: number = Date.now(),
): boolean {
    if (!token || !secret) return false;
    const [rawExpires, provided, ...rest] = token.split('.');
    if (!rawExpires || !provided || rest.length > 0) return false;
    const expires = Number(rawExpires);
    if (!Number.isInteger(expires) || expires * 1000 < nowMs) return false;
    const expected = hmacSignature(`${userId}.${expires}`, secret);
    return safeEqual(provided, expected);
}
