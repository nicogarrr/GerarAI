import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
    createAlertResult: vi.fn(), deleteAlert: vi.fn(), getUserAlertsResult: vi.fn(),
    getTelegramStatus: vi.fn(), getRecentTriggeredAlerts: vi.fn(),
}));
const state = vi.hoisted(() => ({ query: '' }));
const { review, showErrorToast } = vi.hoisted(() => ({ review: vi.fn(), showErrorToast: vi.fn() }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(state.query) }));
vi.mock('@/lib/actions/alerts.actions', () => api);
vi.mock('@/lib/actions/research.actions', () => ({ reviewResearchExpectations: review }));
vi.mock('@/lib/toast', () => ({ showErrorToast }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('@/components/search/TickerSearchInput', () => ({
    TickerSearchInput: ({ id, value, onValueChange, onSelect, ariaLabel }: { id: string; value: string; onValueChange: (value: string) => void; onSelect: (stock: { symbol: string }) => void; ariaLabel: string }) => (
        <><input id={id} value={value} aria-label={ariaLabel} onChange={(event) => onValueChange(event.target.value)} /><button type="button" onClick={() => onSelect({ symbol: 'msft' })}>Seleccionar ticker sintético</button></>
    ),
}));
vi.mock('@/components/research/ExternalNewsHeadline', () => ({
    ExternalNewsHeadline: ({ headline, url }: { headline: string; url?: string | null }) => <a href={url ?? undefined}>{headline}</a>,
}));

import AlertsManager from '@/components/alerts/AlertsManager';
import { AppError } from '@/lib/types/errors';
import { toast } from 'sonner';
import type { Alert, TriggeredAlertDelivery } from '@/lib/actions/alerts.actions';

const alert: Alert = {
    _id: '42', symbol: 'AAPL', type: 'price_above', condition: { operator: '>', value: 150 },
    isActive: true, createdAt: '2026-10-01T12:00:00Z', updatedAt: '2026-10-01T12:00:00Z',
    channels: ['in_app'], triggerCount: 0,
};
const delivery = (overrides: Partial<TriggeredAlertDelivery> = {}): TriggeredAlertDelivery => ({
    id: 1, title: 'Aviso sintético', message: 'Detalle de prueba', severity: 'info', status: 'active',
    alert_type: 'price_above', channels: [], deliveries: {}, ticker: null, triggeredAt: null,
    sourceUrl: null, companyName: null, eventDate: null, eventDateSource: null, eventForm: null,
    createdAt: '2026-10-01T12:00:00Z', ...overrides,
});

beforeEach(() => {
    vi.clearAllMocks();
    state.query = '';
    api.getUserAlertsResult.mockReset().mockResolvedValue({ ok: true, alerts: [alert] });
    api.getTelegramStatus.mockReset().mockResolvedValue(null);
    api.getRecentTriggeredAlerts.mockReset().mockResolvedValue([]);
    api.createAlertResult.mockReset().mockResolvedValue({ ok: true, alert });
    api.deleteAlert.mockReset().mockResolvedValue(undefined);
    review.mockReset().mockResolvedValue(undefined);
});

async function load() {
    render(<AlertsManager />);
    return screen.findByRole('button', { name: /^Eliminar alerta:/ });
}
async function create() {
    state.query = 'symbol=AAPL&type=price_above&value=150';
    render(<AlertsManager />);
    const button = await screen.findByRole('button', { name: 'Crear alerta' });
    fireEvent.click(button);
    return button;
}

describe('alerts manager load and mutation contracts', () => {
    it.each([
        ['session', 'Tu sesión ha caducado. Vuelve a entrar para ver tus alertas.'],
        ['forbidden', 'No tienes permiso para ver estas alertas.'],
        ['rate', 'Demasiadas peticiones. Espera un momento y reintenta.'],
        ['offline', 'No se pudieron cargar tus alertas. Reintenta en unos segundos.'],
        ['unknown', 'No se pudieron cargar tus alertas. Reintenta en unos segundos.'],
    ])('keeps the proven load cause %s and offers retry without duplicate toasts', async (cause, message) => {
        api.getUserAlertsResult.mockResolvedValueOnce({ ok: false, cause });
        render(<AlertsManager />);
        expect(await screen.findByRole('alert')).toHaveTextContent(message);
        if (cause === 'session') expect(screen.getByRole('link', { name: 'Iniciar sesión' })).toHaveAttribute('href', '/sign-in');
        else expect(screen.queryByRole('link', { name: 'Iniciar sesión' })).not.toBeInTheDocument();
        expect(showErrorToast).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
        await screen.findByRole('button', { name: /^Eliminar alerta:/ });
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('shows a neutral load failure if the action throws, not a false empty list', async () => {
        api.getUserAlertsResult.mockRejectedValueOnce(new Error('synthetic backend failure'));
        render(<AlertsManager />);
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar tus alertas');
        expect(screen.queryByText('No tienes alertas configuradas')).not.toBeInTheDocument();
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('does not lose rules when optional Telegram/history reads fail', async () => {
        api.getTelegramStatus.mockRejectedValueOnce(new Error('offline'));
        api.getRecentTriggeredAlerts.mockRejectedValueOnce(new Error('offline'));
        await load();
        expect(screen.getByText('AAPL: Precio por encima de 150')).toBeVisible();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('creates once, closes the form and refreshes only after server success', async () => {
        let finish!: (result: unknown) => void;
        api.createAlertResult.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
        const button = await create();
        await waitFor(() => expect(button).toBeDisabled());
        expect(screen.getByRole('dialog')).toBeVisible();
        fireEvent.click(button);
        expect(api.createAlertResult).toHaveBeenCalledTimes(1);
        expect(toast.success).not.toHaveBeenCalled();
        await act(async () => { finish({ ok: true, alert }); });
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(api.createAlertResult).toHaveBeenCalledWith(expect.objectContaining({ symbol: 'AAPL', condition: { operator: '>', value: 150 } }));
        expect(toast.success).toHaveBeenCalledWith('Alerta creada');
        expect(api.getUserAlertsResult.mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    it('keeps duplicate rejection inside the form without a false success', async () => {
        api.createAlertResult.mockResolvedValueOnce({ ok: false, cause: 'duplicate', message: 'Aviso sintético duplicado' });
        await create();
        await waitFor(() => expect(toast.info).toHaveBeenCalledWith('Aviso sintético duplicado'));
        expect(screen.getByRole('dialog')).toBeVisible();
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('keeps an offline create retry reachable inside the modal', async () => {
        api.createAlertResult.mockRejectedValueOnce(new AppError('synthetic outage', 'RESEARCH_API_ERROR', 503));
        await create();
        const failure = await screen.findByRole('alert');
        expect(failure).toHaveFocus();
        expect(screen.getByRole('dialog')).toContainElement(failure);
        fireEvent.click(within(failure).getByRole('button', { name: 'Reintentar' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(api.createAlertResult).toHaveBeenCalledTimes(2);
        expect(showErrorToast).not.toHaveBeenCalled();
    });

    it('routes a non-offline create exception to the mutation error surface', async () => {
        const error = new Error('synthetic business exception');
        api.createAlertResult.mockRejectedValueOnce(error);
        await create();
        await waitFor(() => expect(showErrorToast).toHaveBeenCalledWith(error, expect.objectContaining({ duplicateMessage: 'Ya tienes esta alerta configurada.' })));
        expect(screen.getByRole('dialog')).toBeVisible();
    });

    it('does not delete on the first click or cancel; deletes after explicit confirmation', async () => {
        const button = await load();
        fireEvent.click(button);
        expect(api.deleteAlert).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
        expect(api.deleteAlert).not.toHaveBeenCalled();
        fireEvent.click(button);
        api.getUserAlertsResult.mockResolvedValueOnce({ ok: true, alerts: [] });
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        await screen.findByText('No tienes alertas configuradas');
        expect(api.deleteAlert).toHaveBeenCalledExactlyOnceWith('42');
        expect(toast.success).toHaveBeenCalledWith('Alerta eliminada');
    });

    it('keeps the rule and offers a retry when deletion fails', async () => {
        const error = new Error('synthetic deletion failure');
        api.deleteAlert.mockRejectedValueOnce(error);
        fireEvent.click(await load());
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        await waitFor(() => expect(showErrorToast).toHaveBeenCalledWith(error, expect.objectContaining({ onRetry: expect.any(Function) })));
        expect(screen.getByRole('button', { name: /^Eliminar alerta:/ })).toBeEnabled();
        expect(toast.success).not.toHaveBeenCalled();
        const retry = showErrorToast.mock.calls[0][1].onRetry as () => Promise<void>;
        await act(async () => { await retry(); });
        expect(api.deleteAlert).toHaveBeenCalledTimes(2);
    });

    it('blocks repeated review while pending and refreshes its state after success', async () => {
        let finish!: () => void;
        review.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
        await load();
        const button = screen.getByRole('button', { name: 'Ejecutar revisión de expectativas de AAPL' });
        fireEvent.click(button);
        await waitFor(() => expect(button).toBeDisabled());
        fireEvent.click(button);
        expect(review).toHaveBeenCalledExactlyOnceWith('AAPL');
        await act(async () => { finish(); });
        expect(button).toBeEnabled();
        expect(toast.success).toHaveBeenCalledWith('Revisión de expectativas lanzada para AAPL');
    });

    it('offers a review retry without claiming success on failure', async () => {
        const error = new Error('synthetic review failure');
        review.mockRejectedValueOnce(error);
        await load();
        fireEvent.click(screen.getByRole('button', { name: 'Ejecutar revisión de expectativas de AAPL' }));
        await waitFor(() => expect(showErrorToast).toHaveBeenCalledWith(error, expect.objectContaining({ onRetry: expect.any(Function) })));
        expect(toast.success).not.toHaveBeenCalled();
        await act(async () => { await showErrorToast.mock.calls[0][1].onRetry(); });
        expect(review).toHaveBeenCalledTimes(2);
    });

    it.each([true, false])('reports the returned Telegram configuration without guessing (%s)', async (configured) => {
        api.getTelegramStatus.mockResolvedValueOnce({ configured });
        await load();
        expect(screen.getByRole('note')).toHaveTextContent(configured ? 'Canal Telegram configurado' : 'Telegram sin configurar');
    });

    it('shows stale rule evaluation and saved trigger times, not a fresh successful comparison', async () => {
        api.getUserAlertsResult.mockResolvedValueOnce({ ok: true, alerts: [{ ...alert,
            lastTriggered: '2026-10-02T12:00:00Z', lastEvaluatedAt: '2026-10-03T12:00:00Z',
            lastResultStatus: 'skipped_stale_observation', channels: [], triggerCount: 2,
        }] });
        await load();
        expect(screen.getByText(/dato desactualizado/)).toBeVisible();
        expect(screen.getByText(/Disparada por última vez/)).toBeVisible();
        expect(screen.getByRole('link', { name: 'Ver research →' })).toHaveAttribute('href', '/research/AAPL');
    });

    it('preserves source links and distinguishes delivery evidence from absent records', async () => {
        api.getRecentTriggeredAlerts.mockResolvedValueOnce([
            delivery({ channels: ['email', 'telegram', 'push'], deliveries: {
                email: { status: 'delivered' }, telegram: { status: 'failed', error: 'synthetic failure' },
            }, ticker: 'AAPL', sourceUrl: 'https://source.example.invalid/document', triggeredAt: '2026-10-02T12:00:00Z' }),
            delivery({ id: 2, title: 'Noticia sobre AAPL: Titular sintético', alert_type: 'tracked_news', ticker: 'AAPL', eventHeadline: 'Titular sintético' }),
            delivery({ id: 3 }),
        ]);
        await load();
        expect(screen.getByText('correo: entregada')).toBeVisible();
        expect(screen.getByText('Telegram: fallida')).toHaveAttribute('title', 'synthetic failure');
        expect(screen.getByText('notificación: sin registro de entrega')).toBeVisible();
        expect(screen.getAllByText('sin canales')).toHaveLength(2);
        expect(screen.getByRole('link', { name: 'Abrir documento' })).toHaveAttribute('href', 'https://source.example.invalid/document');
        expect(screen.getByRole('link', { name: 'Abrir documento' })).toHaveAttribute('rel', 'noopener noreferrer');
        expect(screen.getByText('Titular sintético')).toBeVisible();
        expect(screen.getByText('Titular sintético')).not.toHaveAttribute('href');
    });

    it('creates from the empty state and updates the chosen ticker and localized price', async () => {
        api.getUserAlertsResult.mockResolvedValue({ ok: true, alerts: [] });
        render(<AlertsManager />);
        fireEvent.click(await screen.findByRole('button', { name: 'Crear la primera alerta' }));
        fireEvent.change(screen.getByLabelText('Símbolo'), { target: { value: 'aapl' } });
        expect(screen.getByLabelText('Símbolo')).toHaveValue('AAPL');
        fireEvent.click(screen.getByRole('button', { name: 'Seleccionar ticker sintético' }));
        expect(screen.getByLabelText('Símbolo')).toHaveValue('MSFT');
        fireEvent.change(screen.getByLabelText('Precio (divisa de la cotización)'), { target: { value: '152,50' } });
        fireEvent.click(screen.getByRole('button', { name: 'Crear alerta' }));
        await waitFor(() => expect(api.createAlertResult).toHaveBeenCalledWith({ symbol: 'MSFT', type: 'price_above', condition: { operator: '>', value: 152.5 } }));
    });

    it.each([
        ['price_below', 'Precio por debajo de', '<'],
        ['price_above', 'Precio por encima de', '>'],
        ['news', 'Nueva noticia', '<'],
        ['earnings', 'Resultados', '<'],
    ])('syncs type selection %s with its request semantics', async (type, label, operator) => {
        state.query = 'symbol=AAPL&type=price_change&value=150';
        render(<AlertsManager />);
        const selector = await screen.findByRole('combobox', { name: 'Tipo de alerta' });
        fireEvent.click(selector);
        fireEvent.click(await screen.findByRole('option', { name: label }));
        fireEvent.click(screen.getByRole('button', { name: 'Crear alerta' }));
        await waitFor(() => expect(api.createAlertResult).toHaveBeenCalledWith(expect.objectContaining({ type, condition: { operator, value: type === 'news' || type === 'earnings' ? '150' : 150 } })));
    });

    it('preserves the percentage direction selected by the user', async () => {
        state.query = 'symbol=AAPL&type=price_above&value=5';
        render(<AlertsManager />);
        fireEvent.click(await screen.findByRole('combobox', { name: 'Tipo de alerta' }));
        fireEvent.click(await screen.findByRole('option', { name: 'Cambio de precio %' }));
        fireEvent.click(screen.getByRole('combobox', { name: 'Operador' }));
        fireEvent.click(await screen.findByRole('option', { name: 'Menor que (<)' }));
        fireEvent.click(screen.getByRole('button', { name: 'Crear alerta' }));
        await waitFor(() => expect(api.createAlertResult).toHaveBeenCalledWith(expect.objectContaining({ type: 'price_change', condition: { operator: '<', value: 5 } })));
    });

    it.each(['0', '-1', 'not-a-number'])('rejects invalid price %s without creating a rule', async (value) => {
        state.query = `symbol=AAPL&type=price_below&value=${value}`;
        render(<AlertsManager />);
        fireEvent.click(await screen.findByRole('button', { name: 'Crear alerta' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(value === 'not-a-number' ? 'Introduce un valor numérico válido' : 'El precio debe ser mayor que 0'));
        expect(api.createAlertResult).not.toHaveBeenCalled();
    });

    it('renders rule kinds and both percentage directions without mislabeling unknown types', async () => {
        api.getUserAlertsResult.mockResolvedValueOnce({ ok: true, alerts: [
            { ...alert, _id: '1', type: 'price_change', condition: { operator: '>', value: 5 } },
            { ...alert, _id: '2', type: 'price_change', condition: { operator: '<', value: 5 } },
            { ...alert, _id: '3', type: 'news' },
            { ...alert, _id: '4', type: 'earnings' },
            { ...alert, _id: '5', type: 'unknown_from_old_data', symbol: '' },
        ] });
        render(<AlertsManager />);
        expect(await screen.findByText('AAPL: Cambio de precio % mayor a 5%')).toBeVisible();
        expect(screen.getByText('AAPL: Cambio de precio % menor a 5%')).toBeVisible();
        expect(screen.getByText('AAPL: Nueva noticia')).toBeVisible();
        expect(screen.getByText('AAPL: Resultados')).toBeVisible();
        expect(screen.getAllByRole('button', { name: /Ejecutar revisión de expectativas/ })).toHaveLength(4);
    });

});
