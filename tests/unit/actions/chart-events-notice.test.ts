import { beforeEach, describe, expect, it, vi } from 'vitest';

const { request, user, translate } = vi.hoisted(() => ({ request: vi.fn(), user: vi.fn(), translate: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: user }));
vi.mock('@/lib/research/client', () => ({ researchRequest: request }));
vi.mock('@/lib/i18n/server', () => ({ getT: async () => translate }));

import { getChartEvents } from '@/lib/actions/price-events.actions';

// El texto fijo que emite company_events_service.stored_holding (backend).
const BACKEND_NOTICE = 'Coste medio no comparable: faltan cantidades/costes válidos o las divisas no coinciden. No se ha inferido un tipo de cambio.';

describe('getChartEvents: aviso de calidad del coste medio', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        user.mockResolvedValue({ id: 'tenant-one' });
        translate.mockImplementation((key: string) => `<${key}>`);
    });

    it('propaga holding.notice traducido cuando coincide con el texto fijo del backend', async () => {
        request.mockImplementation(async (url: string) => url.includes('/events/timeline')
            ? { events: [], holding: { average_cost: null, first_buy_date: '2026-01-10', notice: BACKEND_NOTICE } }
            : { currency: 'USD', consensus: { mean: null } });
        const result = await getChartEvents('AAPL', '2026-01-01', '2026-02-01');
        expect(result.holdingNotice).toBe('<research.chart.holdingNotice>');
        expect(result.averageCost).toBeNull();
        expect(result.firstBuyDate).toBe('2026-01-10');
        expect(translate).toHaveBeenCalledWith('research.chart.holdingNotice');
    });

    it('deja pasar tal cual un aviso que no reconoce', async () => {
        request.mockImplementation(async (url: string) => url.includes('/events/timeline')
            ? { events: [], holding: { average_cost: null, first_buy_date: null, notice: 'aviso nuevo del motor' } }
            : { currency: null, consensus: null });
        const result = await getChartEvents('AAPL', '2026-01-01', '2026-02-01');
        expect(result.holdingNotice).toBe('aviso nuevo del motor');
        expect(translate).not.toHaveBeenCalled();
    });

    it('sin posición o con coste comparable no hay aviso', async () => {
        request.mockImplementation(async (url: string) => url.includes('/events/timeline')
            ? { events: [], holding: { average_cost: 151.25, first_buy_date: '2026-01-10' } }
            : { currency: 'USD', consensus: { mean: 200 } });
        const result = await getChartEvents('AAPL', '2026-01-01', '2026-02-01');
        expect(result.holdingNotice).toBeNull();
        expect(result.averageCost).toBe(151.25);
        request.mockResolvedValue({ events: [], holding: null });
        expect((await getChartEvents('AAPL', '2026-01-01', '2026-02-01')).holdingNotice).toBeNull();
    });

    it('el fallo del timeline deja el aviso en null sin romper el objetivo', async () => {
        request.mockImplementation(async (url: string) => {
            if (url.includes('/events/timeline')) throw new Error('backend caído');
            return { currency: 'USD', consensus: { mean: 210 } };
        });
        const result = await getChartEvents('AAPL', '2026-01-01', '2026-02-01');
        expect(result.holdingNotice).toBeNull();
        expect(result.events).toEqual([]);
        expect(result.target).toBe(210);
    });

    it('rechaza ticker o fechas con forma no válida antes de llamar al motor', async () => {
        await expect(getChartEvents('aapl!', '2026-01-01', '2026-02-01')).rejects.toThrow('Rango o empresa no válido');
        await expect(getChartEvents('AAPL', '01/01/2026', '2026-02-01')).rejects.toThrow('Rango o empresa no válido');
        expect(request).not.toHaveBeenCalled();
    });

    it('filtra eventos incompletos y objetivos no positivos o no finitos', async () => {
        request.mockImplementation(async (url: string) => url.includes('/events/timeline')
            ? { events: [{ date: '2026-01-05', source: 's', kind: 'news' }, { date: '', source: 's' }, null], holding: null }
            : { currency: 'USD', consensus: { mean: -3 } });
        let result = await getChartEvents('AAPL', '2026-01-01', '2026-02-01');
        expect(result.events).toHaveLength(1);
        expect(result.target).toBeNull();
        expect(result.targetCurrency).toBe('USD');
        request.mockImplementation(async (url: string) => url.includes('/events/timeline')
            ? { events: [] }
            : { consensus: { mean: Number.POSITIVE_INFINITY } });
        result = await getChartEvents('AAPL', '2026-01-01', '2026-02-01');
        expect(result.target).toBeNull();
        expect(result.targetCurrency).toBeNull();
    });
});
