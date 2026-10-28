import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, getResearchCompanyBasics, quoteSymbolFor } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    getResearchCompanyBasics: vi.fn(),
    quoteSymbolFor: vi.fn(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest }));
vi.mock('@/lib/actions/market-workspace.actions', () => ({ getResearchCompanyBasics }));
vi.mock('@/lib/market/quote-symbol', () => ({ quoteSymbolFor }));

import { getListingAnalystTargets } from '@/lib/actions/analyst-targets.actions';

beforeEach(() => { vi.clearAllMocks(); });

describe('getListingAnalystTargets', () => {
    it('ticker vacío -> null sin llamar', async () => {
        expect(await getListingAnalystTargets('   ')).toBeNull();
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('quoteSymbol null explícito -> no se consulta nada (ticker desnudo = otro emisor)', async () => {
        expect(await getListingAnalystTargets('ALM.MC', null)).toBeNull();
        expect(getResearchCompanyBasics).not.toHaveBeenCalled();
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('omitido -> resuelve el listado via master; sin correspondencia -> null', async () => {
        getResearchCompanyBasics.mockResolvedValue(null);
        quoteSymbolFor.mockReturnValue(null);
        expect(await getListingAnalystTargets('ALM.MC')).toBeNull();
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('consenso ok: media > 0, divisa declarada en mayúsculas, firmas = filas', async () => {
        researchRequest.mockResolvedValue({
            status: 'available', source: 'Yahoo Finance', fetched_at: 1777000000,
            currency: 'usd', consensus: { mean: 185.5 }, rows: [{}, {}, {}], note: null,
        });
        const result = await getListingAnalystTargets('AAPL', 'AAPL');
        expect(result).toMatchObject({ status: 'available', mean: 185.5, currency: 'USD', firms: 3, fetchedAt: 1777000000 });
        expect(String(researchRequest.mock.calls[0][0])).toContain('/api/companies/AAPL/analyst-targets');
    });

    it('media 0, negativa o NaN -> null (un consenso inválido no es una cifra)', async () => {
        for (const mean of [0, -5, Number.NaN]) {
            researchRequest.mockResolvedValue({ status: 'available', consensus: { mean }, rows: [] });
            expect((await getListingAnalystTargets('AAPL', 'AAPL'))!.mean).toBeNull();
        }
    });

    it('defaults honestos: status/fuente cuando el backend no los trae; divisa vacía -> null', async () => {
        researchRequest.mockResolvedValue({ consensus: null, currency: '  ' });
        const result = await getListingAnalystTargets('AAPL', 'AAPL');
        expect(result).toMatchObject({ status: 'unavailable', mean: null, currency: null, firms: 0, source: expect.stringContaining('no oficial') });
    });

    it('backend caído -> null (la celda muestra su estado, nunca cifras inventadas)', async () => {
        researchRequest.mockRejectedValue(new Error('503'));
        expect(await getListingAnalystTargets('AAPL', 'AAPL')).toBeNull();
    });
});
