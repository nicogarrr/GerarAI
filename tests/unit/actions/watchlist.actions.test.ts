import { beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
    invalidate: vi.fn(),
    revalidatePath: vi.fn(),
    getResearchCompanyBasics: vi.fn(),
}));
vi.mock('next/cache', () => ({ revalidatePath: m.revalidatePath }));
vi.mock('@/lib/research/client', () => ({ researchRequest: m.researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/cache/requestCache', () => ({ requestCache: { invalidate: m.invalidate } }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: m.requireAuthenticatedUser }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getStockQuote: vi.fn(), getStockValuationBasics: vi.fn() }));
vi.mock('@/lib/actions/market-workspace.actions', () => ({ getResearchCompanyBasics: m.getResearchCompanyBasics }));

import { AppError } from '@/lib/types/errors';
import {
    addToWatchlist,
    addToWatchlistCanonical,
    getWatchlist,
    getWatchlistState,
    removeFromWatchlist,
} from '@/lib/actions/watchlist.actions';

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    m.requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-w' });
});

describe('getWatchlistState', () => {
    it('mapea las entradas del backend con su fecha de alta', async () => {
        m.researchRequest.mockResolvedValueOnce([
            { symbol: 'AAPL', created_at: '2026-10-01T10:00:00Z', analysis: { status: 'ready' } },
        ]);
        const state = await getWatchlistState();
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist');
        expect(state.unavailable).toBe(false);
        expect(state.items).toHaveLength(1);
        expect(state.items[0].symbol).toBe('AAPL');
        expect(state.items[0].addedAt.toISOString()).toBe('2026-10-01T10:00:00.000Z');
        expect(state.items[0].analysis).toEqual({ status: 'ready' });
    });

    it('una respuesta que no es lista es «no disponible», no una watchlist vacía (F386)', async () => {
        m.researchRequest.mockResolvedValueOnce({ detail: 'boom' });
        expect(await getWatchlistState()).toEqual({ items: [], unavailable: true });
    });

    it('un fallo del backend o de la sesión es «no disponible»', async () => {
        m.researchRequest.mockRejectedValueOnce(new AppError('down', 'RESEARCH_API_ERROR', 503));
        expect(await getWatchlistState()).toEqual({ items: [], unavailable: true });
        m.requireAuthenticatedUser.mockRejectedValueOnce(new AppError('no session', 'AUTH_ERROR', 401));
        expect(await getWatchlistState()).toEqual({ items: [], unavailable: true });
    });

    it('una watchlist vacía de verdad está disponible', async () => {
        m.researchRequest.mockResolvedValueOnce([]);
        expect(await getWatchlistState()).toEqual({ items: [], unavailable: false });
        m.researchRequest.mockResolvedValueOnce([{ symbol: 'MSFT', created_at: '2026-01-02T00:00:00Z' }]);
        expect((await getWatchlist()).map((i) => i.symbol)).toEqual(['MSFT']);
    });
});

describe('addToWatchlist', () => {
    it('envía el símbolo en mayúsculas, invalida la caché del usuario y revalida las páginas', async () => {
        m.researchRequest.mockResolvedValueOnce({});
        const result = await addToWatchlist('vod.l', 'Vodafone');
        expect(result).toEqual({ success: true });
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist', {
            method: 'POST',
            body: JSON.stringify({ symbol: 'VOD.L', company: 'Vodafone' }),
        });
        expect(m.invalidate).toHaveBeenCalledWith('watchlist:tenant-w');
        expect(m.revalidatePath).toHaveBeenCalledWith('/watchlist');
        expect(m.revalidatePath).toHaveBeenCalledWith('/research/VOD.L');
    });

    it('sin empresa no manda el campo company', async () => {
        m.researchRequest.mockResolvedValueOnce({});
        await addToWatchlist('mc.pa');
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist', expect.objectContaining({
            body: JSON.stringify({ symbol: 'MC.PA' }),
        }));
    });

    it('un duplicado devuelve el código y el mensaje para el toast, sin invalidar nada', async () => {
        m.researchRequest.mockRejectedValueOnce(new AppError('dup', 'DUPLICATE_ERROR', 409));
        const result = await addToWatchlist('AAPL');
        expect(result).toEqual({ success: false, code: 'duplicate', message: 'Ya sigues este ticker.' });
        expect(m.invalidate).not.toHaveBeenCalled();
        expect(m.revalidatePath).not.toHaveBeenCalled();
    });

    it('el motor caído es «offline» (el toast ofrece Reintentar)', async () => {
        m.researchRequest.mockRejectedValueOnce(new AppError('down', 'RESEARCH_API_ERROR', 502));
        const result = await addToWatchlist('AAPL');
        expect(result.success).toBe(false);
        expect(result.code).toBe('offline');
    });
});

describe('addToWatchlistCanonical', () => {
    it('guarda el ticker canónico del master (SAN.MC -> SAN) con su nombre', async () => {
        m.getResearchCompanyBasics.mockResolvedValueOnce({ ticker: 'san', name: 'Banco Santander' });
        m.researchRequest.mockResolvedValueOnce({});
        expect(await addToWatchlistCanonical(' san.mc ')).toEqual({ success: true });
        expect(m.getResearchCompanyBasics).toHaveBeenCalledWith('SAN.MC');
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist', expect.objectContaining({
            body: JSON.stringify({ symbol: 'SAN', company: 'Banco Santander' }),
        }));
    });

    it('si el master no conoce el símbolo usa el literal normalizado y respeta la empresa dada', async () => {
        m.getResearchCompanyBasics.mockResolvedValueOnce(null);
        m.researchRequest.mockResolvedValueOnce({});
        await addToWatchlistCanonical('xyz.l', 'XYZ plc');
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist', expect.objectContaining({
            body: JSON.stringify({ symbol: 'XYZ.L', company: 'XYZ plc' }),
        }));
    });
});

describe('removeFromWatchlist', () => {
    it('codifica el símbolo en la ruta y revalida', async () => {
        m.researchRequest.mockResolvedValueOnce(undefined);
        expect(await removeFromWatchlist('BRK.B')).toEqual({ success: true });
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist/BRK.B', { method: 'DELETE' });
        m.researchRequest.mockResolvedValueOnce(undefined);
        await removeFromWatchlist('A/B');
        expect(m.researchRequest).toHaveBeenLastCalledWith('/api/watchlist/A%2FB', { method: 'DELETE' });
        expect(m.invalidate).toHaveBeenCalledWith('watchlist:tenant-w');
    });

    it('quitar uno que ya no está (404) es éxito idempotente y revalida (#2677)', async () => {
        // Quitado antes en otra pestaña: el objetivo ya se cumple; un error con
        // «Reintentar» dejaba la fila vieja y un reintento que siempre falla.
        m.researchRequest.mockRejectedValueOnce(new AppError('Ese ticker no está en tu watchlist', 'NOT_FOUND', 404));
        const result = await removeFromWatchlist('GONE');
        expect(result).toEqual({ success: true });
        expect(m.revalidatePath).toHaveBeenCalledWith('/watchlist');
    });
});
