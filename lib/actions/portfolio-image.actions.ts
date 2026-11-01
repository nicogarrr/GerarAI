'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest, jsonBody } from '@/lib/research/client';
import { requestCache } from '@/lib/cache/requestCache';
import { AppError, getFriendlyErrorMessage } from '@/lib/types/errors';
import type { ConfirmedImageRow, ImageActionResult, ImageInstrument, ImagePreview, ImageReview } from '@/lib/portfolio/image-import';
import { backendMessageForRequest } from '@/lib/research/backend-error-locale';

/**
 * El backend responde 403/422/503 con el motivo ya en español y accionable;
 * se devuelve tal cual. Lo demás pasa por el traductor común. Un redirect de
 * Next (sesión caducada) se relanza para que navegue.
 */
async function imageCall<T>(fn: () => Promise<T>): Promise<ImageActionResult<T>> {
    try {
        return { ok: true, data: await fn() };
    } catch (error) {
        const digest = (error as { digest?: unknown })?.digest;
        if (typeof digest === 'string' && digest.startsWith('NEXT_')) throw error;
        if (error instanceof AppError && error.code === 'RESEARCH_API_ERROR' && [403, 422, 503].includes(error.statusCode) && error.message) {
            return { ok: false, error: await backendMessageForRequest(error.message) };
        }
        return { ok: false, error: getFriendlyErrorMessage(error) };
    }
}

export async function previewPortfolioImage(imageBase64: string): Promise<ImageActionResult<ImagePreview>> {
    await requireAuthenticatedUser();
    if (!imageBase64 || imageBase64.length > 2_796_204) return { ok: false, error: 'La imagen debe ocupar como máximo 2 MB' };
    return imageCall(() => researchRequest<ImagePreview>('/api/portfolio/image/preview', { method: 'POST', body: jsonBody({ image_base64: imageBase64 }), timeoutMs: 20_000 }));
}

export async function searchImageInstrument(query: string): Promise<ImageActionResult<ImageInstrument[]>> {
    await requireAuthenticatedUser();
    return imageCall(() => researchRequest<ImageInstrument[]>(`/api/portfolio/image/instruments?q=${encodeURIComponent(query.slice(0, 80))}`));
}

export async function reviewPortfolioImage(imageHash: string, rows: ConfirmedImageRow[]): Promise<ImageActionResult<ImageReview>> {
    await requireAuthenticatedUser();
    return imageCall(() => researchRequest<ImageReview>('/api/portfolio/image/review', { method: 'POST', body: jsonBody({ image_hash: imageHash, rows }), timeoutMs: 30_000 }));
}

export async function confirmPortfolioImage(reviewId: number): Promise<ImageActionResult<{ status: string; positions_imported: number }>> {
    const user = await requireAuthenticatedUser();
    const result = await imageCall(() => researchRequest<{ status: string; positions_imported: number }>('/api/portfolio/image/confirm', { method: 'POST', body: jsonBody({ review_id: reviewId, confirmed: true }) }));
    if (result.ok) {
        for (const suffix of ['positions', 'summary', 'transactions', 'scores', 'tearsheet', 'dividends', 'quality']) requestCache.invalidate(`portfolio:${user.id}:${suffix}`);
    }
    return result;
}
