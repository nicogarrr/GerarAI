/**
 * Huella de IP para el limite por conexion. Solo servidor (usa node:crypto): no
 * importar desde componentes cliente; por eso vive aparte de `access-request.ts`.
 */
import { createHash } from 'node:crypto';

/**
 * Huella de la IP para limitar abusos sin guardar la IP en claro. La sal sale
 * del entorno; sin sal sigue siendo un hash (no reversible a simple vista).
 */
export function hashIp(ip: string, salt: string): string {
    return createHash('sha256').update(`${salt}|${ip.trim()}`).digest('hex').slice(0, 32);
}

/**
 * IP del cliente para el limite. El primer valor de `x-forwarded-for` lo puede
 * fijar el propio cliente, asi que no se usa: se prefiere `x-real-ip` (la pone la
 * plataforma) y, si falta, el ULTIMO valor de `x-forwarded-for` (el que anade el
 * proxy mas cercano). `unknown` si no hay ninguno.
 */
export function clientIp(forwardedFor: string | null | undefined, realIp?: string | null): string {
    const real = (realIp ?? '').trim();
    if (real) return real;
    const parts = (forwardedFor ?? '').split(',').map((p) => p.trim()).filter(Boolean);
    return parts[parts.length - 1] || 'unknown';
}
