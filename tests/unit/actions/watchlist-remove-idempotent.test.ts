import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, requestCacheInvalidate, revalidatePath } = vi.hoisted(() => ({
    researchRequest: vi.fn<(...args: any[]) => any>(async () => undefined),
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(async () => ({ id: 'user-1' })),
    requestCacheInvalidate: vi.fn<(...args: any[]) => any>(),
    revalidatePath: vi.fn<(...args: any[]) => any>(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/cache/requestCache', () => ({ requestCache: { invalidate: requestCacheInvalidate, get: vi.fn(), set: vi.fn() } }));
vi.mock('next/cache', () => ({ revalidatePath }));

import { AppError } from '@/lib/types/errors';
import { removeFromWatchlist } from '@/lib/actions/watchlist.actions';

beforeEach(() => {
    vi.clearAllMocks();
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
});

/**
 * E2E (user-flows/watchlist): quitar un valor desde una pestaña vieja, cuando
 * ya se había quitado en otra, mostraba el toast de error «Ese ticker no está
 * en tu watchlist» con «Reintentar» (que vuelve a fallar siempre) y la fila
 * se quedaba. El objetivo del usuario —que no esté— ya se cumple: un 404 del
 * DELETE es éxito idempotente y refresca la lista.
 */
describe('removeFromWatchlist', () => {
    it('quita y revalida', async () => {
        researchRequest.mockResolvedValueOnce(undefined);
        expect(await removeFromWatchlist('VOD.L')).toEqual({ success: true });
        expect(researchRequest).toHaveBeenCalledWith('/api/watchlist/VOD.L', { method: 'DELETE' });
        expect(revalidatePath).toHaveBeenCalledWith('/watchlist');
    });

    it('un valor que ya no estaba (404) cuenta como quitado y revalida la lista', async () => {
        researchRequest.mockRejectedValueOnce(new AppError('Ese ticker no está en tu watchlist', 'RESEARCH_API_ERROR', 404));
        expect(await removeFromWatchlist('VOD.L')).toEqual({ success: true });
        expect(requestCacheInvalidate).toHaveBeenCalledWith('watchlist:user-1');
        expect(revalidatePath).toHaveBeenCalledWith('/watchlist');
        expect(revalidatePath).toHaveBeenCalledWith('/research/VOD.L');
    });

    it('otros errores siguen siendo fallo (con mensaje)', async () => {
        researchRequest.mockRejectedValueOnce(new AppError('Servicio caído', 'RESEARCH_API_ERROR', 503));
        const res = await removeFromWatchlist('VOD.L');
        expect(res.success).toBe(false);
        expect(revalidatePath).not.toHaveBeenCalled();
    });
});
