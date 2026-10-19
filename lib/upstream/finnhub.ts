/**
 * Cliente HTTP de Finnhub. Modulo interno SIN 'use server'.
 *
 * Motivo de separarlo de lib/actions/finnhub.actions.ts: en un fichero
 * 'use server' todo export de nivel superior se registra como Server Action y
 * por tanto es invocable por HTTP con la cookie de sesion. Exportar
 * `fetchJSON` desde ahi convertia un helper con URL arbitraria en un endpoint
 * publico: cualquier usuario autenticado podia pedirle un GET a
 * http://169.254.169.254/... y recibir el cuerpo. Solo comprobaba *quien*
 * llama, nunca *a donde* va la peticion.
 *
 * Este modulo no se exporta como action, asi que la URL solo puede
 * construirse desde codigo del servidor.
 */

import { withFetchDeadline } from '@/lib/upstream/fetch-deadline';
import { TIMEOUTS } from '@/lib/constants';
import { ExternalAPIError, RateLimitError, toAppError } from '@/lib/types/errors';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { redactUrl, sanitizeCause } from '@/lib/upstream/redact';

export { redactUrl };

/**
 * Función helper para fetch con manejo de errores apropiado
 * Lanza errores tipados en lugar de retornar arrays vacíos silenciosamente
 */
export async function fetchJSON<T>(url: string, revalidateSeconds?: number, timeoutMs: number = TIMEOUTS.API_REQUEST): Promise<T> {
    await requireAuthenticatedUser();
    // Para datos críticos como precios y noticias, usar cache mínimo (30-60 segundos)
    // Para datos estáticos como perfiles, permitir cache más largo
    const options: RequestInit & { next?: { revalidate?: number } } = revalidateSeconds && revalidateSeconds > 0
        ? { cache: 'force-cache', next: { revalidate: revalidateSeconds } }
        : { cache: 'no-store' };

    try {
        return await withFetchDeadline(async (signal) => {
            const res = await fetch(url, { ...options, signal });

            if (!res.ok) {
                const safeUrl = redactUrl(url);
                // Lanzar errores apropiados en lugar de retornar arrays vacíos
                if (res.status === 429) {
                    throw new RateLimitError(`API rate limit reached for ${safeUrl}`);
                }

                if (res.status >= 500) {
                    throw new ExternalAPIError(
                        `External API error (${res.status}) for ${safeUrl}`,
                        'finnhub',
                        { status: res.status, statusText: res.statusText }
                    );
                }

                throw new ExternalAPIError(
                    `Failed to fetch ${safeUrl}: ${res.status} ${res.statusText}`,
                    'finnhub',
                    { status: res.status }
                );
            }

            // Verificar que la respuesta sea JSON antes de parsear
            const contentType = res.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                // Finnhub a veces devuelve HTML cuando hay rate limit o errores
                const text = await res.text();
                if (text.startsWith('<!DOCTYPE') || text.startsWith('<html')) {
                    throw new RateLimitError(`Finnhub returned HTML instead of JSON (likely rate limited)`);
                }
                // Intentar parsear de todos modos si no es HTML
                try {
                    return JSON.parse(text) as T;
                } catch {
                    throw new ExternalAPIError(`Invalid response format from Finnhub`, 'finnhub');
                }
            }

            return (await res.json()) as T;
        }, timeoutMs);
    } catch (error: unknown) {

        // Si es un error de nuestra aplicación, re-lanzarlo
        if (error instanceof RateLimitError || error instanceof ExternalAPIError) {
            throw error;
        }

        // Manejar otros errores. La causa NUNCA es el error crudo: fetch
        // rechaza con la URL completa (?token=...) en el mensaje, y esa
        // cadena acababa en originalError/cause del error de frontera, en
        // los console.error de los actions y en una posible serializacion.
        const appError = toAppError(error);
        const safeUrl = redactUrl(url);
        const safeCause = sanitizeCause(error);
        if ((error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name)) || appError.message.includes('AbortError') || appError.message.includes('aborted')) {
            throw new ExternalAPIError(
                `Request timeout for ${safeUrl}`,
                'finnhub',
                safeCause
            );
        }

        throw new ExternalAPIError(
            `Unexpected error fetching ${safeUrl}`,
            'finnhub',
            safeCause
        );
    }
}
