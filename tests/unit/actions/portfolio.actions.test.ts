import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, invalidate } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
    invalidate: vi.fn(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/cache/memoryTTL', () => ({ cachedFetch: (_k: string, fetcher: () => Promise<unknown>) => fetcher() }));
vi.mock('@/lib/cache/requestCache', () => ({ requestCache: { invalidate } }));

import { AppError } from '@/lib/types/errors';
import {
    addTransaction,
    updateTransaction,
    deleteTransaction,
    deleteHolding,
    getPortfolioTransactions,
    getPortfolioTransactionPage,
    getPortfolioSummary,
    getPortfolioScores,
    quickAddPosition,
    getPortfolioWithWeights,
    refreshPortfolioHoldings,
    updateAllPortfolioPrices,
    importFromIBKR,
    importIBKRXml,
    importIBKRCsv,
    getPortfolioTearsheet,
    getPortfolioForecast,
    getPortfolioDividendProjection,
    getPortfolioDataQuality,
    syncPortfolioDividends,
} from '@/lib/actions/portfolio.actions';

const position = (over: object = {}) => ({
    ticker: 'AAPL', quantity: 10, average_cost: 100,
    market_price: 150, market_value: 1500, unrealized_pnl: 500,
    valuation_hold: null,
    currency: 'USD', native_currency: 'USD', base_currency: 'EUR',
    realized_pnl: 0, cost_basis: 1000, as_of: '2026-10-27',
    market_value_native: 1500, market_value_base: 1350,
    cost_basis_native: 1000, unrealized_pnl_native: 500,
    cost_basis_base: 900, unrealized_pnl_base: 450, realized_pnl_base: 0, fx_rate: 0.9,
    first_buy_date: '2025-01-01', holding_days: 300, fiscal_bucket: 'corto_plazo',
    ...over,
});

const backendSummary = (over: object = {}) => ({
    total_value: 3350, equity_value: 1350, cash: { EUR: 2000 },
    status: 'ok', base_currency: 'EUR', missing_fx: [], ...over,
});

const seedSummary = (positions: object[], summary: object = {}) => {
    researchRequest.mockImplementation(async (path: string) => {
        if (path === '/api/portfolio/positions') return positions;
        if (path === '/api/portfolio/summary') return backendSummary(summary);
        if (path === '/api/portfolio/data-quality') throw new Error('sin calidad');
        throw new AppError('404', 'RESEARCH_API_ERROR', 404);
    });
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    delete process.env.FINNHUB_API_KEY;
});

describe('aislamiento por usuario', () => {
    it('pedir la cartera de otro -> AuthorizationError antes de cualquier llamada', async () => {
        await expect(getPortfolioSummary('tenant-two')).rejects.toMatchObject({ code: 'AUTHORIZATION_ERROR' });
        expect(researchRequest).not.toHaveBeenCalled();
    });
});

describe('addTransaction / updateTransaction', () => {
    it('valida cantidad, precio y comisiones antes de escribir', async () => {
        await expect(addTransaction('tenant-one', 'AAPL', 'buy', 0, 100, new Date())).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await expect(addTransaction('tenant-one', 'AAPL', 'buy', 1, -5, new Date())).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await expect(addTransaction('tenant-one', 'AAPL', 'buy', 1, 100, new Date(), undefined, 'USD', -1)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await expect(updateTransaction('tenant-one', '1', 'AAPL', 'buy', 1, 100, new Date(), undefined, 'USD', Number.NaN)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('escribe con ticker/divisa en mayúsculas, fecha YYYY-MM-DD e invalida las lecturas', async () => {
        researchRequest.mockResolvedValue({});
        const result = await addTransaction('tenant-one', 'aapl', 'buy', 2, 150.5, new Date('2026-10-27T15:00:00Z'), undefined, 'eur', 1.5);
        expect(result).toEqual({ success: true });
        expect(JSON.parse(researchRequest.mock.calls[0][1].body)).toEqual({
            ticker: 'AAPL', action: 'buy', quantity: 2, price: 150.5,
            trade_date: '2026-10-27', notes: null, currency: 'EUR', fees: 1.5,
        });
        for (const suffix of ['positions', 'summary', 'transactions', 'scores', 'tearsheet', 'dividends']) {
            expect(invalidate).toHaveBeenCalledWith(`portfolio:tenant-one:${suffix}`);
        }
    });

    it('update sin comisiones omite fees (el backend conserva la registrada)', async () => {
        researchRequest.mockResolvedValue({});
        await updateTransaction('tenant-one', '7', 'AAPL', 'sell', 1, 160, new Date('2026-10-27T00:00:00Z'));
        expect(JSON.parse(researchRequest.mock.calls[0][1].body)).not.toHaveProperty('fees');
        expect(researchRequest.mock.calls[0][0]).toBe('/api/portfolio/transactions/7');
        expect(researchRequest.mock.calls[0][1].method).toBe('PUT');
    });
});

describe('deleteTransaction / deleteHolding', () => {
    it('borra y reinvalida', async () => {
        researchRequest.mockResolvedValue({});
        await deleteTransaction('tenant-one', '7');
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/transactions/7', { method: 'DELETE' });
        await deleteHolding('tenant-one', 'aapl');
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/holdings/AAPL', { method: 'DELETE' });
        expect(invalidate).toHaveBeenCalledWith('portfolio:tenant-one:positions');
    });
});

describe('lecturas de transacciones', () => {
    const tx = { id: 1, ticker: 'AAPL', action: 'buy', quantity: 1, price: 100, fees: 1, currency: 'USD', trade_date: '2026-01-01', created_at: 'c', updated_at: 'u' };

    it('mapea la lista completa', async () => {
        researchRequest.mockResolvedValue([tx]);
        const [item] = await getPortfolioTransactions('tenant-one');
        expect(item).toMatchObject({ _id: '1', symbol: 'AAPL', type: 'buy', fees: 1, date: '2026-01-01' });
    });

    it('offset inseguro (negativo, decimal, NaN) cae a 0', async () => {
        researchRequest.mockResolvedValue({ items: [], total: 0 });
        for (const offset of [-5, 1.5, Number.NaN]) {
            const page = await getPortfolioTransactionPage('tenant-one', offset);
            expect(page.offset).toBe(0);
            expect(researchRequest).toHaveBeenLastCalledWith('/api/portfolio/transactions/page?limit=50&offset=0', { fast: true });
        }
    });
});

describe('getPortfolioSummary: dinero y suspensión de valoración', () => {
    it('mapea posiciones, ordena por valor desc y suma la caja por divisa', async () => {
        seedSummary([
            position({ ticker: 'PEQUE', market_value_base: 100 }),
            position({ ticker: 'GRANDE', market_value_base: 5000 }),
        ], { cash: { EUR: 1000, USD: 500 } });
        const summary = await getPortfolioSummary('tenant-one');
        expect(summary.holdings.map((h) => h.symbol)).toEqual(['GRANDE', 'PEQUE']);
        expect(summary.cash).toBe(1500);
        expect(summary.totalCost).toBe(1800);
        expect(summary.totalGain).toBe(900);
        expect(summary.totalGainPercent).toBeCloseTo(50, 1);
        expect(summary.quality).toBeNull(); // data-quality caída -> null, no rompe
    });

    it('valoración en suspensión: currentPrice null y fxMissing declarado, nunca un precio rancio', async () => {
        seedSummary([position({ valuation_hold: { reason: 'split sin verificar', effective_date: '2026-10-01', since: null } })]);
        const [h] = (await getPortfolioSummary('tenant-one')).holdings;
        expect(h.currentPrice).toBeNull();
        expect(h.valuationHold).toEqual({ reason: 'split sin verificar', effectiveDate: '2026-10-01' });
        expect(h.fxMissing).toBe(true);
    });

    it('bases nulas -> fxMissing/valueMissing; coste 0 -> gainPercent 0 (no NaN)', async () => {
        seedSummary([position({ market_value_base: null, cost_basis_base: null, unrealized_pnl_base: null })]);
        const [h] = (await getPortfolioSummary('tenant-one')).holdings;
        expect(h.fxMissing).toBe(true);
        expect(h.valueMissing).toBe(true);
        expect(h.cost).toBe(0);
        expect(h.gainPercent).toBe(0);
    });
});

describe('getPortfolioScores: null es ausencia, no un cero', () => {
    it('sin posiciones -> todos null', async () => {
        seedSummary([]);
        expect(await getPortfolioScores('tenant-one')).toEqual({
            quality: null, growth: null, value: null, dividend: null, cagr3y: null,
        });
    });

    it('sin métricas cualificadas -> scores null (un fallo del backend no es "tu cartera vale 0/100")', async () => {
        seedSummary([position()]);
        const scores = await getPortfolioScores('tenant-one');
        expect(scores.quality).toBeNull();
        expect(scores.growth).toBeNull();
        expect(scores.value).toBeNull();
        expect(scores.dividend).toBeNull();
    });

    it('dividendo: banda 0-6 % con cobertura; endpoint caído -> null', async () => {
        seedSummary([position()]);
        researchRequest.mockImplementation(async (path: string) => {
            if (path === '/api/portfolio/positions') return [position()];
            if (path === '/api/portfolio/summary') return backendSummary();
            if (path === '/api/portfolio/data-quality') throw new Error('x');
            if (path === '/api/portfolio/snapshots') return [];
            if (path === '/api/portfolio/tearsheet') return { status: 'ok', metrics: null, exposure: null };
            if (path === '/api/portfolio/dividends') return { portfolio_yield: 0.03, coverage: { positions_with_dividend_data: 2 } };
            throw new AppError('404', 'RESEARCH_API_ERROR', 404);
        });
        expect((await getPortfolioScores('tenant-one')).dividend).toBe(50);
        researchRequest.mockImplementation(async (path: string) => {
            if (path === '/api/portfolio/positions') return [position()];
            if (path === '/api/portfolio/summary') return backendSummary();
            if (path === '/api/portfolio/data-quality') throw new Error('x');
            if (path === '/api/portfolio/dividends') throw new Error('caído');
            return [];
        });
        expect((await getPortfolioScores('tenant-one')).dividend).toBeNull();
    });
});

describe('quickAddPosition / getPortfolioWithWeights', () => {
    it('quickAddPosition es una compra hoy', async () => {
        researchRequest.mockResolvedValue({});
        expect(await quickAddPosition('tenant-one', 'AAPL', 2, 100)).toEqual({ success: true });
        expect(JSON.parse(researchRequest.mock.calls[0][1].body).action).toBe('buy');
    });

    it('pesos en % del valor total; cartera vacía -> 0', async () => {
        seedSummary([position({ market_value_base: 1350 })], { total_value: 2700 });
        const [h] = await getPortfolioWithWeights('tenant-one');
        expect(h.weight).toBeCloseTo(50, 1);
        seedSummary([], { total_value: 0 });
        expect((await getPortfolioWithWeights('tenant-one')).length).toBe(0);
    });
});

describe('refreshPortfolioHoldings: declara lo que SE ESCRIBIÓ', () => {
    it('sin posiciones -> ValidationError', async () => {
        await expect(refreshPortfolioHoldings([])).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
    });

    it('sin clave de proveedor: ok false, todo skipped, y NO se invalida nada', async () => {
        const result = await refreshPortfolioHoldings([{ symbol: 'AAPL' } as never]);
        expect(result).toEqual({ ok: false, updated: [], skipped: ['AAPL'], failed: [] });
        expect(invalidate).not.toHaveBeenCalled();
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('con clave: escribe los precios con cotización, declara skipped/failed y relee', async () => {
        process.env.FINNHUB_API_KEY = 'key';
        vi.resetModules();
        const mod = await import('@/lib/actions/portfolio.actions');
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            if (String(url).includes('AAPL')) return { ok: true, json: async () => ({ c: 151 }) } as Response;
            return { ok: false } as Response;
        }));
        researchRequest.mockImplementation(async (path: string, opts?: { method?: string }) => {
            if (opts?.method === 'PATCH') return {};
            if (path === '/api/portfolio/positions') return [position()];
            if (path === '/api/portfolio/summary') return backendSummary();
            if (path === '/api/portfolio/data-quality') throw new Error('x');
            throw new AppError('404', 'RESEARCH_API_ERROR', 404);
        });
        const result = await mod.refreshPortfolioHoldings([{ symbol: 'AAPL' } as never, { symbol: 'MSFT' } as never]);
        expect(result).toMatchObject({ ok: true, updated: ['AAPL'], skipped: ['MSFT'], failed: [] });
        expect(invalidate).toHaveBeenCalled();
        vi.unstubAllGlobals();
    });

    it('escritura OK + relectura KO -> holdingsStale, no error (los precios están grabados)', async () => {
        process.env.FINNHUB_API_KEY = 'key';
        vi.resetModules();
        const mod = await import('@/lib/actions/portfolio.actions');
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ c: 151 }) } as Response)));
        researchRequest.mockImplementation(async (path: string, opts?: { method?: string }) => {
            if (opts?.method === 'PATCH') return {};
            throw new Error('relectura caída');
        });
        const input = [{ symbol: 'AAPL' } as never];
        const result = await mod.refreshPortfolioHoldings(input);
        expect(result).toMatchObject({ ok: true, updated: ['AAPL'], holdingsStale: true, holdings: input });
        vi.unstubAllGlobals();
    });
});

describe('updateAllPortfolioPrices: invalida y relee (nunca dispara el refresh masivo)', () => {
    it('devuelve summary + scores frescos', async () => {
        seedSummary([]);
        const result = await updateAllPortfolioPrices('tenant-one');
        expect(invalidate).toHaveBeenCalledWith('portfolio:tenant-one:positions');
        expect(result.summary.holdings).toEqual([]);
        expect(result.scores.quality).toBeNull();
        expect(researchRequest.mock.calls.some((c) => String(c[0]).includes('refresh-market'))).toBe(false);
    });
});

describe('importaciones IBKR: el rechazo 4xx llega con su motivo', () => {
    it('OK -> invalida y devuelve el resultado', async () => {
        researchRequest.mockResolvedValue({ status: 'ok', positions_imported: 3 });
        expect(await importFromIBKR('tenant-one')).toMatchObject({ status: 'ok', positions_imported: 3 });
        expect(invalidate).toHaveBeenCalled();
    });

    it('422 con motivo -> resultado rejected, no excepción enmascarada', async () => {
        researchRequest.mockRejectedValue(new AppError('La cuenta del Flex no coincide', 'RESEARCH_API_ERROR', 422));
        const result = await importFromIBKR('tenant-one');
        expect(result).toMatchObject({ status: 'rejected', message: 'La cuenta del Flex no coincide', positions_imported: 0 });
        researchRequest.mockRejectedValue(new AppError('XML mal formado', 'RESEARCH_API_ERROR', 400));
        expect(await importIBKRXml('tenant-one', '<xml/>')).toMatchObject({ status: 'rejected' });
        researchRequest.mockRejectedValue(new AppError('cabecera ausente', 'RESEARCH_API_ERROR', 422));
        expect(await importIBKRCsv('tenant-one', 'a,b')).toMatchObject({ status: 'rejected' });
    });

    it('mensaje que es solo el código HTTP no sirve como motivo -> propaga', async () => {
        researchRequest.mockRejectedValue(new AppError('422 Unprocessable Entity', 'RESEARCH_API_ERROR', 422));
        await expect(importFromIBKR('tenant-one')).rejects.toThrow('422');
    });

    it('500 -> propaga (no es un rechazo del usuario)', async () => {
        researchRequest.mockRejectedValue(new AppError('boom', 'RESEARCH_API_ERROR', 500));
        await expect(importFromIBKR('tenant-one')).rejects.toMatchObject({ statusCode: 500 });
    });
});

describe('lecturas simples', () => {
    it('tearsheet caído -> null (nunca lanza por falta de historial)', async () => {
        researchRequest.mockRejectedValue(new Error('500'));
        expect(await getPortfolioTearsheet('tenant-one')).toBeNull();
        expect(await getPortfolioDataQuality('tenant-one')).toBeNull();
    });

    it('forecast y proyección de dividendos van sin caché', async () => {
        researchRequest.mockResolvedValue({ positions: [] });
        await getPortfolioForecast();
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/forecast', { fast: true });
        await getPortfolioDividendProjection();
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/dividends/projection', { fast: true });
    });

    it('syncPortfolioDividends sincroniza e invalida', async () => {
        researchRequest.mockResolvedValue({});
        await syncPortfolioDividends('tenant-one');
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/dividends/sync', { method: 'POST' });
        expect(invalidate).toHaveBeenCalledWith('portfolio:tenant-one:dividends');
    });
});
