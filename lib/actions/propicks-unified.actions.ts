'use server';

/**
 * Capa de datos de las pantallas unificadas de ProPicks (Oportunidades y
 * Seguimiento) sobre el contrato B1 `propicks-unified-v1` (GET
 * /api/propicks/unified). Módulo 'use server': exporta SOLO funciones async
 * (guard server-actions-async-exports). Los tipos y la lógica pura viven en
 * lib/propicks/unified.ts.
 */

import { hasRenderableUnifiedShape } from '@/lib/propicks/unified-response';
import { researchRequest } from '@/lib/research/client';
import { AppError, ExternalAPIError } from '@/lib/types/errors';
import { type UnifiedErrorKind, type UnifiedFetch, type UnifiedResult } from '@/lib/propicks/unified';

function errorKindFor(error: unknown): { errorKind: UnifiedErrorKind; retryAfterSeconds: number | null } {
    if (error instanceof AppError && error.code === 'RESEARCH_API_ERROR') {
        if (error.statusCode === 401) return { errorKind: 'unauthenticated', retryAfterSeconds: null };
        if (error.statusCode === 403) return { errorKind: 'forbidden', retryAfterSeconds: null };
        if (error.statusCode === 429) {
            const cause = error.cause as { retryAfterSeconds?: unknown } | undefined;
            const seconds = typeof cause?.retryAfterSeconds === 'number' && Number.isFinite(cause.retryAfterSeconds)
                ? cause.retryAfterSeconds
                : null;
            return { errorKind: 'rate_limited', retryAfterSeconds: seconds };
        }
        return { errorKind: 'unavailable', retryAfterSeconds: null };
    }
    if (error instanceof ExternalAPIError) {
        return { errorKind: error.message.includes('timeout') ? 'timeout' : 'unavailable', retryAfterSeconds: null };
    }
    return { errorKind: 'unavailable', retryAfterSeconds: null };
}

/** GET /api/propicks/unified con clasificación honesta del fallo (nunca lanza). */
export async function getUnifiedProPicks(): Promise<UnifiedFetch> {
    try {
        const result = await researchRequest<UnifiedResult>('/api/propicks/unified', { fast: true });
        if (!hasRenderableUnifiedShape(result)) {
            console.error(`[propicks-unified] respuesta no renderizable`);
            return { ok: false, errorKind: 'invalid_response', retryAfterSeconds: null };
        }
        return { ok: true, result };
    } catch (error) {
        const { errorKind, retryAfterSeconds } = errorKindFor(error);
        console.error(`[propicks-unified] ${errorKind}:`, error instanceof Error ? error.message : error);
        return { ok: false, errorKind, retryAfterSeconds };
    }
}
