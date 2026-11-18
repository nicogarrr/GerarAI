import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, fetchDatedChanges } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
    fetchDatedChanges: vi.fn(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/market/dated-change', () => ({ fetchDatedChanges }));

import { formatNumber } from '@/lib/format';
import {
    exportScreenerResults,
    getScreenerStocksReal,
    getScreenerStocksRealWithStatus,
    getFairValueReading,
    runScreenerEngine,
    runSavedScreenerEngine,
    getSavedScreenerEngines,
    type ScreenerResult,
} from '@/lib/actions/screener.actions';

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
});

describe('exportScreenerResults', () => {
    const row: ScreenerResult = {
        symbol: 'AAPL', name: 'Apple', price: 150, change: 1.5, changePercent: 1,
        marketCap: 2_500_000_000_000, pe: 25, pb: 30, roe: 150, volume: 5_000_000,
        beta: 1.2, sector: 'Technology', exchange: 'NASDAQ', type: 'Stock',
    };

    it('genera CSV con cabecera y valores formateados igual que la UI', async () => {
        const csv = await exportScreenerResults([row]);
        const lines = csv.split('\n');
        expect(lines[0]).toBe('Symbol,Name,Price,Change,Change %,Market Cap,P/E,P/B,ROE,Volume,Beta,Sector,Exchange,Type');
        expect(lines).toHaveLength(2);
        const fmt = (v: number, d = 2) => formatNumber(v, { minimumFractionDigits: d, maximumFractionDigits: d });
        expect(lines[1]).toBe([
            'AAPL', 'Apple', fmt(150), fmt(1.5), fmt(1),
            formatNumber(2_500_000_000_000, { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
            fmt(25), fmt(30), fmt(150),
            formatNumber(5_000_000, { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
            fmt(1.2), 'Technology', 'NASDAQ', 'Stock',
        ].join(','));
    });

    it('exige sesión', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('No autenticado'));
        await expect(exportScreenerResults([row])).rejects.toThrow('No autenticado');
    });
});

describe('getScreenerStocksRealWithStatus', () => {
    const baseRow = {
        symbol: 'AAPL', name: 'Apple', price: 999, change: 0, changePercent: 0,
        marketCap: 1, volume: 1, prevClose: 998, sector: 'Technology', exchange: 'NASDAQ',
        type: 'Stock', pe: null, pb: null, roe: null, beta: null,
    };

    it('construye la query (limit 25 por defecto) y sobrescribe precio con cierres datados', async () => {
        researchRequest.mockResolvedValue({ screener: [baseRow], universe_size: 1200 });
        fetchDatedChanges.mockResolvedValue({
            AAPL: { price: 151.2, currency: 'USD', change: 1.2, changePercent: 0.8, previousClose: 150, date: '2026-10-27' },
        });
        const result = await getScreenerStocksRealWithStatus({ marketCapMoreThan: 1e9, sector: 'Technology' });
        expect(researchRequest).toHaveBeenCalledWith('/api/screeners/real?marketCapMoreThan=1000000000&sector=Technology&limit=25', { cache: 'no-store' });
        expect(result.rows[0]).toMatchObject({ price: 151.2, currency: 'USD', changePercent: 0.8, priceDate: '2026-10-27' });
        expect(result.refreshing).toBe(false);
        expect(result.unavailable).toBe(false);
        expect(result.universeSize).toBe(1200);
    });

    it('sin cierre datado conserva la fila original', async () => {
        researchRequest.mockResolvedValue({ screener: [baseRow] });
        fetchDatedChanges.mockResolvedValue({});
        const result = await getScreenerStocksReal();
        expect(result[0].price).toBe(999);
        expect(result[0].priceDate).toBeUndefined();
    });

    it('vacío + unavailable + sin refresh -> unavailable (proveedor sin datos, no filtro sin resultados)', async () => {
        researchRequest.mockResolvedValue({ screener: [], unavailable: true });
        fetchDatedChanges.mockResolvedValue({});
        const result = await getScreenerStocksRealWithStatus();
        expect(result).toEqual({ rows: [], refreshing: false, unavailable: true, universeSize: null });
    });

    it('vacío con refresh en vuelo -> refreshing, no unavailable', async () => {
        researchRequest.mockResolvedValue({ screener: [], unavailable: true, refreshing: true });
        fetchDatedChanges.mockResolvedValue({});
        const result = await getScreenerStocksRealWithStatus();
        expect(result.refreshing).toBe(true);
        expect(result.unavailable).toBe(false);
    });
});

describe('getFairValueReading: la misma cifra en todas las páginas', () => {
    it('valor válido con fuente conocida -> lectura con precedencia declarada', async () => {
        researchRequest.mockResolvedValue({ value: 185.5, source: 'tesis', label: 'Tesis publicada v3', publishable: true, as_of: '2026-10-20' });
        expect(await getFairValueReading('AAPL')).toEqual({
            value: 185.5, publishable: true, source: 'tesis', label: 'Tesis publicada v3', asOf: '2026-10-20',
        });
        expect(researchRequest).toHaveBeenCalledWith('/api/valuation/AAPL/fair-value', { cache: 'no-store' });
    });

    it('preserva los avisos de la lectura sin cambiar la cifra', async () => {
        researchRequest.mockResolvedValue({ value: 42, source: 'motor', warnings: ['Model cap applied', null, 'Model cap applied'] });
        expect(await getFairValueReading('AAPL')).toMatchObject({ value: 42, source: 'motor', warnings: ['Model cap applied'] });
    });

    it('sin valor, valor <= 0 o fuente desconocida -> null (nunca un número inventado)', async () => {
        researchRequest.mockResolvedValue({ value: null, source: 'tesis' });
        expect(await getFairValueReading('AAPL')).toBeNull();
        researchRequest.mockResolvedValue({ value: -3, source: 'motor' });
        expect(await getFairValueReading('AAPL')).toBeNull();
        researchRequest.mockResolvedValue({ value: 100, source: 'gpt-lo-dijo' });
        expect(await getFairValueReading('AAPL')).toBeNull();
    });

    it('motor orientativo no publicable se declara publishable=false con etiqueta por defecto', async () => {
        researchRequest.mockResolvedValue({ value: 42, source: 'motor_orientativo' });
        expect(await getFairValueReading('AAPL')).toEqual({
            value: 42, publishable: false, source: 'motor_orientativo', label: 'Valor justo', asOf: null,
        });
    });

    it('fallo de red -> null', async () => {
        researchRequest.mockRejectedValue(new Error('boom'));
        expect(await getFairValueReading('AAPL')).toBeNull();
    });
});

describe('motor de screener', () => {
    const criteria = [{ left: 'pe', operator: '<' as const, right: '15' }];

    it('sin criterios -> error antes de llamar al backend', async () => {
        await expect(runScreenerEngine([])).rejects.toThrow('Define al menos un criterio');
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('POST con fórmula y dirección por defecto desc', async () => {
        researchRequest.mockResolvedValue({ results: [] });
        await runScreenerEngine(criteria);
        expect(researchRequest).toHaveBeenCalledWith('/api/screeners/run', {
            method: 'POST',
            body: JSON.stringify({ criteria, ranking_formula: null, ranking_direction: 'desc' }),
        });
    });

    it('filtro guardado: id no entero o <= 0 -> error sin llamada', async () => {
        await expect(runSavedScreenerEngine(0)).rejects.toThrow('Filtro no válido');
        await expect(runSavedScreenerEngine(1.5)).rejects.toThrow('Filtro no válido');
        expect(researchRequest).not.toHaveBeenCalled();
        researchRequest.mockResolvedValue({ results: [] });
        await runSavedScreenerEngine(3);
        expect(researchRequest).toHaveBeenCalledWith('/api/screeners/screens/3/run', { method: 'POST' });
    });

    it('lista de filtros guardados sin caché', async () => {
        researchRequest.mockResolvedValue([{ id: 1, name: 'Marco Nico' }]);
        expect(await getSavedScreenerEngines()).toEqual([{ id: 1, name: 'Marco Nico' }]);
        expect(researchRequest).toHaveBeenCalledWith('/api/screeners/screens', { cache: 'no-store' });
    });
});
