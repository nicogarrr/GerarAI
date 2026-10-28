import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest } = vi.hoisted(() => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));

import { getMoneyFlowThemes, getMoneyFlow, getFlowHoldings } from '@/lib/actions/money-flows.actions';

beforeEach(() => vi.clearAllMocks());

describe('getMoneyFlowThemes', () => {
    it('lista de temas tal cual llega', async () => {
        researchRequest.mockResolvedValue([{ theme_id: 'ia', total: 10 }]);
        expect(await getMoneyFlowThemes()).toEqual([{ theme_id: 'ia', total: 10 }]);
        expect(researchRequest).toHaveBeenCalledWith('/api/market/flows/themes', { fast: true });
    });

    it('endpoint ausente o roto -> lista vacía (la página se pinta igualmente)', async () => {
        researchRequest.mockRejectedValue(new Error('404'));
        expect(await getMoneyFlowThemes()).toEqual([]);
        researchRequest.mockResolvedValue({ detail: 'no list' });
        expect(await getMoneyFlowThemes()).toEqual([]);
    });
});

describe('getMoneyFlow', () => {
    it('detalle válido: escapa el themeId en la URL', async () => {
        researchRequest.mockResolvedValue({ spenders: [] });
        expect(await getMoneyFlow('IA & chips')).toEqual({ spenders: [] });
        expect(researchRequest).toHaveBeenCalledWith('/api/market/flows/themes/IA%20%26%20chips', { timeoutMs: 60_000 });
    });

    it('payload sin lista de spenders -> null, nunca un flujo incompleto', async () => {
        researchRequest.mockResolvedValue({ spenders: 'no-array' });
        expect(await getMoneyFlow('ia')).toBeNull();
        researchRequest.mockResolvedValue(null);
        expect(await getMoneyFlow('ia')).toBeNull();
    });

    it('error del backend -> null', async () => {
        researchRequest.mockRejectedValue(new Error('500'));
        expect(await getMoneyFlow('ia')).toBeNull();
    });
});

describe('getFlowHoldings: solape con cartera y seguimiento', () => {
    it('normaliza tickers a mayúsculas y descarta entradas vacías', async () => {
        researchRequest
            .mockResolvedValueOnce([{ ticker: 'aapl' }, { ticker: 'msft' }, { ticker: null }])
            .mockResolvedValueOnce([{ symbol: 'AAPL' }, { symbol: 'goog' }]);
        const result = await getFlowHoldings();
        expect(result.unavailable).toBe(false);
        expect([...result.portfolio].sort()).toEqual(['AAPL', 'MSFT']);
        expect([...result.watchlist].sort()).toEqual(['AAPL', 'GOOG']);
    });

    it('cualquier fallo o forma rara -> no disponible, nunca un "no tienes nada" inventado', async () => {
        researchRequest.mockRejectedValue(new Error('boom'));
        expect(await getFlowHoldings()).toEqual({ portfolio: new Set(), watchlist: new Set(), unavailable: true });
        researchRequest.mockResolvedValueOnce({}).mockResolvedValueOnce([]);
        expect((await getFlowHoldings()).unavailable).toBe(true);
    });
});
