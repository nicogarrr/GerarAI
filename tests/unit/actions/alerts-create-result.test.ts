import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, invalidate } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
    invalidate: vi.fn(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/cache/memoryTTL', () => ({ cachedFetch: (_key: string, fetcher: () => Promise<unknown>) => fetcher() }));
vi.mock('@/lib/cache/requestCache', () => ({ requestCache: { invalidate } }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));

import { AppError } from '@/lib/types/errors';
import * as actions from '@/lib/actions/alerts.actions';

const input = { symbol: 'zzzqx', type: 'price_above' as const, condition: { operator: '>' as const, value: 250.5 } };

// Suite E2E de flujos (28-oct-2026): un símbolo con formato válido pero
// inexistente devolvía 422 del backend, la server action lo LANZABA (POST
// /alerts 500) y en producción Next enmascara el mensaje: el usuario leía
// «el motor no responde, reintenta» para un símbolo que no existe.
describe('createAlertResult', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        requireAuthenticatedUser.mockResolvedValue({ id: 'u1' });
    });

    it('un 422 «Símbolo no reconocido» vuelve como resultado con su mensaje, no como error', async () => {
        researchRequest
            .mockResolvedValueOnce({ id: 1, ticker: 'ZZZQX' })
            .mockRejectedValueOnce(new AppError('Símbolo no reconocido: ZZZQX. Comprueba que exista en bolsa.', 'RESEARCH_API_ERROR', 422));
        const createAlertResult = (actions as Record<string, unknown>).createAlertResult as
            ((value: typeof input) => Promise<unknown>) | undefined;
        expect(typeof createAlertResult).toBe('function');
        await expect(createAlertResult!(input)).resolves.toEqual({
            ok: false,
            cause: 'validation',
            message: 'Símbolo no reconocido: ZZZQX. Comprueba que exista en bolsa.',
        });
    });

    it('un 409 es «ya la tienes», no un fallo', async () => {
        researchRequest
            .mockResolvedValueOnce({ id: 1, ticker: 'AAPL' })
            .mockRejectedValueOnce(new AppError('duplicate', 'RESEARCH_API_ERROR', 409));
        await expect(actions.createAlertResult({ ...input, symbol: 'AAPL' })).resolves.toMatchObject({ ok: false, cause: 'duplicate' });
    });

    it('el motor caído (5xx) sigue lanzando para que el cliente ofrezca reintentar', async () => {
        researchRequest
            .mockResolvedValueOnce({ id: 1, ticker: 'AAPL' })
            .mockRejectedValueOnce(new AppError('Service Unavailable', 'RESEARCH_API_ERROR', 503));
        await expect(actions.createAlertResult({ ...input, symbol: 'AAPL' })).rejects.toThrow('Service Unavailable');
    });
});
