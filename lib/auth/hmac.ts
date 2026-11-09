import { createHmac, timingSafeEqual } from 'node:crypto';

/**
 * Firma HMAC-SHA256 en base64url de un payload opaco (tokens de cuenta:
 * aprobación, reautenticación de borrado). La forma del payload la decide
 * cada flujo; aquí solo vive la cadena criptográfica.
 */
export function hmacSignature(payload: string, secret: string): string {
    return createHmac('sha256', secret).update(payload).digest('base64url');
}

/** Comparación en tiempo constante; longitudes distintas significan no iguales. */
export function safeEqual(a: string, b: string): boolean {
    const ab = Buffer.from(a);
    const bb = Buffer.from(b);
    return ab.length === bb.length && timingSafeEqual(ab, bb);
}
