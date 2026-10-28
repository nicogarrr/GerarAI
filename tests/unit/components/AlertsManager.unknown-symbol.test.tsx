import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Suite E2E de flujos (28-oct-2026): símbolo con formato válido pero
// inexistente. El rechazo del backend llega como resultado y se muestra tal
// cual; el diálogo sigue abierto y no hay «Alerta creada».
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams('symbol=ZZZQX&type=price_above&value=250') }));
const createAlertResult = vi.fn(async () => ({ ok: false, cause: 'validation', message: 'Símbolo no reconocido: ZZZQX. Comprueba que exista en bolsa.' }));
vi.mock('@/lib/actions/alerts.actions', () => ({
    createAlert: vi.fn(async () => { throw new Error('An error occurred in the Server Components render.'); }),
    createAlertResult: (...args: unknown[]) => createAlertResult(...(args as [])),
    deleteAlert: vi.fn(),
    getUserAlertsResult: vi.fn(async () => ({ ok: true, alerts: [] })),
    getTelegramStatus: vi.fn(async () => null), getRecentTriggeredAlerts: vi.fn(async () => []),
}));
vi.mock('@/lib/actions/research.actions', () => ({ reviewResearchExpectations: vi.fn() }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => <input aria-label="Símbolo" /> }));
const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (...a: unknown[]) => toastError(...a), success: (...a: unknown[]) => toastSuccess(...a), info: vi.fn() } }));
import AlertsManager from '@/components/alerts/AlertsManager';

describe('alta de alerta con un símbolo que no existe', () => {
    it('muestra el mensaje del backend, sin «motor caído» ni alta', async () => {
        render(<AlertsManager />);
        fireEvent.click(await screen.findByRole('button', { name: /^Crear/ }));
        await waitFor(() => expect(toastError).toHaveBeenCalled());
        expect(String(toastError.mock.calls[0][0])).toBe('Símbolo no reconocido: ZZZQX. Comprueba que exista en bolsa.');
        expect(toastSuccess).not.toHaveBeenCalled();
        expect(screen.queryByText(/motor de análisis no responde/)).toBeNull();
        expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
});
