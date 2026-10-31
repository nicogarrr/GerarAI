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
import {
    createAlert,
    deleteAlert,
    getUserAlerts,
    getUserAlertsResult,
    getTelegramStatus,
    getRecentTriggeredAlerts,
} from '@/lib/actions/alerts.actions';

const rule = {
    id: 7,
    active: true,
    rule_type: 'price_above',
    condition: { operator: '>', value: 150 },
    channels: ['in_app'],
    trigger_count: 2,
    last_evaluated_at: '2026-10-27T10:00:00Z',
    last_value: '151.2',
    last_result: { status: 'triggered' },
    last_triggered_at: '2026-10-27T10:00:01Z',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-27T10:00:01Z',
    metadata: { ticker: 'AAPL' },
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
});

describe('createAlert', () => {
    it('normaliza el símbolo (trim + mayúsculas), asegura la empresa y crea la regla', async () => {
        researchRequest.mockResolvedValueOnce({}).mockResolvedValueOnce(rule);
        const alert = await createAlert({ symbol: ' aapl ', type: 'price_above', condition: { operator: '>', value: 150 } });
        expect(researchRequest).toHaveBeenNthCalledWith(1, '/api/companies/ensure', expect.objectContaining({ body: JSON.stringify({ ticker: 'AAPL' }) }));
        expect(researchRequest).toHaveBeenNthCalledWith(2, '/api/alerts', expect.objectContaining({
            body: JSON.stringify({ ticker: 'AAPL', alert_type: 'price_above', operator: '>', value: 150 }),
        }));
        expect(alert).toMatchObject({
            _id: '7', symbol: 'AAPL', type: 'price_above', isActive: true,
            triggerCount: 2, lastValue: '151.2', lastResultStatus: 'triggered',
        });
    });

    it('invalida solo las claves de caché del usuario autenticado', async () => {
        researchRequest.mockResolvedValueOnce({}).mockResolvedValueOnce(rule);
        await createAlert({ symbol: 'AAPL', type: 'news', condition: { operator: '==', value: 'any' } });
        expect(invalidate).toHaveBeenCalledWith('alerts:user:tenant-one:active');
        expect(invalidate).toHaveBeenCalledWith('alerts:user:tenant-one:recent:10');
        expect(invalidate).toHaveBeenCalledWith('alerts:user:tenant-one:recent:20');
        expect(invalidate).toHaveBeenCalledTimes(3);
    });

    it.each(['', 'a b', 'MSFT;DROP', 'símbolo-larguísimo-de-más-de-veinte', 'AAPL$'])(
        'símbolo %j -> ValidationError antes de tocar el backend',
        async (symbol) => {
            await expect(createAlert({ symbol, type: 'news', condition: { operator: '==', value: 'x' } }))
                .rejects.toMatchObject({ code: 'VALIDATION_ERROR', field: 'symbol' });
            expect(researchRequest).not.toHaveBeenCalled();
        },
    );

    it.each([0, -5, Number.NaN, 'abc'])(
        'umbral de precio %s -> ValidationError "mayor que 0" (nunca se guarda un umbral inútil)',
        async (value) => {
            await expect(createAlert({ symbol: 'AAPL', type: 'price_below', condition: { operator: '<', value } }))
                .rejects.toMatchObject({ code: 'VALIDATION_ERROR', message: 'El precio debe ser mayor que 0' });
            expect(researchRequest).not.toHaveBeenCalled();
        },
    );

    it('mapea defaults: sin canales -> in_app, sin trigger_count -> 0, sin valor -> null', async () => {
        researchRequest.mockResolvedValueOnce({}).mockResolvedValueOnce({
            ...rule, channels: undefined, trigger_count: undefined, last_value: undefined, last_result: undefined,
        });
        const alert = await createAlert({ symbol: 'AAPL', type: 'news', condition: { operator: '==', value: 'any' } });
        expect(alert.channels).toEqual(['in_app']);
        expect(alert.triggerCount).toBe(0);
        expect(alert.lastValue).toBeNull();
        expect(alert.lastResultStatus).toBeUndefined();
    });
});

describe('getUserAlerts: paginación completa de /api/alerts/rules', () => {
    const pageOf = (from: number, count: number) =>
        Array.from({ length: count }, (_, i) => ({ ...rule, id: from + i }));

    it('pide limit=500 explícito (el defecto del backend, 100, cortaría la lista)', async () => {
        researchRequest.mockResolvedValue([rule]);
        await getUserAlerts();
        expect(researchRequest).toHaveBeenCalledWith('/api/alerts/rules?active=true&limit=500&offset=0');
    });

    it('con página llena sigue pidiendo hasta la primera corta y entrega las 502', async () => {
        researchRequest
            .mockResolvedValueOnce(pageOf(1, 500))
            .mockResolvedValueOnce(pageOf(501, 2))
            .mockResolvedValue([]);
        const alerts = await getUserAlerts();
        expect(alerts).toHaveLength(502);
        expect(researchRequest).toHaveBeenCalledWith('/api/alerts/rules?active=true&limit=500&offset=500');
    });

    it('backend que no avanza (página repetida) -> error, NUNCA lista parcial', async () => {
        researchRequest.mockResolvedValue(pageOf(1, 500));
        await expect(getUserAlerts()).rejects.toThrow(/no avanza/);
        expect(await getUserAlertsResult()).toEqual({ ok: false, cause: 'unknown' });
    });
});

describe('getUserAlertsResult: causa explícita, nunca inventada', () => {
    it('OK -> alertas mapeadas', async () => {
        researchRequest.mockResolvedValue([rule]);
        const result = await getUserAlertsResult();
        expect(result).toEqual({ ok: true, alerts: [expect.objectContaining({ _id: '7', symbol: 'AAPL' })] });
    });

    it('sesión ausente (AUTH_ERROR, lanzada antes del backend) -> session', async () => {
        requireAuthenticatedUser.mockRejectedValue(new AppError('No autenticado', 'AUTH_ERROR', 401));
        expect(await getUserAlertsResult()).toEqual({ ok: false, cause: 'session' });
    });

    it('401 del backend NO es session: puede ser firma de servidor errónea -> unknown', async () => {
        researchRequest.mockRejectedValue(new AppError('401', 'RESEARCH_API_ERROR', 401));
        expect(await getUserAlertsResult()).toEqual({ ok: false, cause: 'unknown' });
    });

    it('403 -> forbidden, 429 -> rate, 5xx -> offline', async () => {
        researchRequest.mockRejectedValue(new AppError('x', 'RESEARCH_API_ERROR', 403));
        expect(await getUserAlertsResult()).toEqual({ ok: false, cause: 'forbidden' });
        researchRequest.mockRejectedValue(new AppError('x', 'RESEARCH_API_ERROR', 429));
        expect(await getUserAlertsResult()).toEqual({ ok: false, cause: 'rate' });
        researchRequest.mockRejectedValue(new AppError('x', 'RESEARCH_API_ERROR', 502));
        expect(await getUserAlertsResult()).toEqual({ ok: false, cause: 'offline' });
    });

    it('fallo de red sin AppError -> offline; error cualquiera -> unknown', async () => {
        researchRequest.mockRejectedValue(new Error('fetch failed: ECONNREFUSED'));
        expect(await getUserAlertsResult()).toEqual({ ok: false, cause: 'offline' });
        researchRequest.mockRejectedValue(new Error('cosa rara'));
        expect(await getUserAlertsResult()).toEqual({ ok: false, cause: 'unknown' });
    });

    it('un redirect de Next se relanza tal cual, nunca se traga como error', async () => {
        const redirect = Object.assign(new Error('NEXT_REDIRECT'), { digest: 'NEXT_REDIRECT;replace;/sign-in;307;' });
        researchRequest.mockRejectedValue(redirect);
        await expect(getUserAlertsResult()).rejects.toBe(redirect);
    });
});

describe('deleteAlert', () => {
    it.each(['abc', '1 OR 1=1', '-3', '1.5', ''])('id %j -> ValidationError antes de borrar', async (alertId) => {
        await expect(deleteAlert(alertId)).rejects.toMatchObject({ code: 'VALIDATION_ERROR', field: 'alertId' });
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('borra la regla e invalida las cachés del usuario', async () => {
        researchRequest.mockResolvedValue({});
        await deleteAlert('7');
        expect(researchRequest).toHaveBeenCalledWith('/api/alerts/rules/7', { method: 'DELETE' });
        expect(invalidate).toHaveBeenCalledWith('alerts:user:tenant-one:active');
    });
});

describe('getTelegramStatus', () => {
    it('devuelve la configuración del backend tal cual', async () => {
        researchRequest.mockResolvedValue({ enabled: true, has_bot_token: true, has_chat_id: false, configured: false });
        expect(await getTelegramStatus()).toEqual({ enabled: true, has_bot_token: true, has_chat_id: false, configured: false });
        expect(researchRequest).toHaveBeenCalledWith('/api/alerts/telegram-status');
    });
});

describe('getRecentTriggeredAlerts', () => {
    const row = {
        id: 3, title: 'AAPL > 150', message: 'Se disparó', severity: 'info', status: 'sent',
        alert_type: 'price_above', channels: ['in_app'], metadata: { deliveries: { in_app: { status: 'sent' } } },
        ticker: 'AAPL', last_triggered_at: '2026-10-27T10:00:01Z', source_url: 'https://sec.gov/x',
        company_name: 'Apple', event_date: '2026-10-26', event_date_source: 'filing', event_form: '8-K',
        event_headline: 'Resultados', created_at: '2026-10-01T00:00:00Z',
    };

    it('mapea la fila con su hora de disparo real y su fuente', async () => {
        researchRequest.mockResolvedValue([row]);
        const [alert] = await getRecentTriggeredAlerts(10);
        expect(researchRequest).toHaveBeenCalledWith('/api/alerts?limit=10');
        expect(alert).toMatchObject({
            id: 3, ticker: 'AAPL', triggeredAt: '2026-10-27T10:00:01Z',
            sourceUrl: 'https://sec.gov/x', companyName: 'Apple', eventHeadline: 'Resultados',
            deliveries: { in_app: { status: 'sent' } },
        });
    });

    it('fila antigua sin last_triggered_at: triggeredAt queda null, no se inventa con created_at', async () => {
        researchRequest.mockResolvedValue([{ ...row, last_triggered_at: null, metadata: undefined }]);
        const [alert] = await getRecentTriggeredAlerts();
        expect(alert.triggeredAt).toBeNull();
        expect(alert.deliveries).toEqual({});
        expect(alert.createdAt).toBe('2026-10-01T00:00:00Z');
    });

    it('respuesta null -> lista vacía', async () => {
        researchRequest.mockResolvedValue(null);
        expect(await getRecentTriggeredAlerts()).toEqual([]);
    });
});
