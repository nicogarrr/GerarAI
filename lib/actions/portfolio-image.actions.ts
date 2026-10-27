'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest, jsonBody } from '@/lib/research/client';
import { requestCache } from '@/lib/cache/requestCache';
import type { ConfirmedImageRow, ImageInstrument, ImagePreview, ImageReview } from '@/lib/portfolio/image-import';

export async function previewPortfolioImage(imageBase64: string): Promise<ImagePreview> {
    await requireAuthenticatedUser();
    if (!imageBase64 || imageBase64.length > 2_796_204) throw new Error('La imagen debe ocupar como máximo 2 MB');
    return researchRequest('/api/portfolio/image/preview', { method: 'POST', body: jsonBody({ image_base64: imageBase64 }), timeoutMs: 20_000 });
}

export async function searchImageInstrument(query: string): Promise<ImageInstrument[]> {
    await requireAuthenticatedUser();
    return researchRequest(`/api/portfolio/image/instruments?q=${encodeURIComponent(query.slice(0, 80))}`);
}

export async function reviewPortfolioImage(imageHash: string, rows: ConfirmedImageRow[]): Promise<ImageReview> {
    await requireAuthenticatedUser();
    return researchRequest('/api/portfolio/image/review', { method: 'POST', body: jsonBody({ image_hash: imageHash, rows }), timeoutMs: 30_000 });
}

export async function confirmPortfolioImage(reviewId: number): Promise<{ status: string; positions_imported: number }> {
    const user = await requireAuthenticatedUser();
    const result = await researchRequest<{ status: string; positions_imported: number }>('/api/portfolio/image/confirm', { method: 'POST', body: jsonBody({ review_id: reviewId, confirmed: true }) });
    for (const suffix of ['positions', 'summary', 'transactions', 'scores', 'tearsheet', 'dividends', 'quality']) requestCache.invalidate(`portfolio:${user.id}:${suffix}`);
    return result;
}
