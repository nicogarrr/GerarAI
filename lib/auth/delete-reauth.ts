import { createHmac, timingSafeEqual } from 'node:crypto';

export const DELETE_REAUTH_HEADER = 'x-cavaai-delete-reauth';
export const DELETE_REAUTH_TTL_MS = 120_000;

function signature(userId: string, expires: number, secret: string): string {
    return createHmac('sha256', secret)
        .update(`${userId}.${expires}`)
        .digest('base64url');
}

export function createDeleteReauthToken(
    userId: string,
    secret: string | undefined,
    nowMs: number = Date.now(),
): string {
    if (!secret) {
        throw new Error('BETTER_AUTH_SECRET is required for account reauthentication');
    }
    const expires = Math.floor((nowMs + DELETE_REAUTH_TTL_MS) / 1000);
    return `${expires}.${signature(userId, expires, secret)}`;
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
    const expected = signature(userId, expires, secret);
    const providedBuffer = Buffer.from(provided);
    const expectedBuffer = Buffer.from(expected);
    return providedBuffer.length === expectedBuffer.length
        && timingSafeEqual(providedBuffer, expectedBuffer);
}
