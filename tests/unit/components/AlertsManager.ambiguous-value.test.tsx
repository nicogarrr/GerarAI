import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Umbral «1,234» (ambiguo: ¿1,234 o 1234?): debe avisar con el mensaje que
// enseña el formato, igual que transacciones/tesis/screener — nunca el
// genérico «valor numérico válido», que no ayuda a corregirlo.
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams('symbol=SAN.MC&type=price_above&value=1,234') }));
const createAlert = vi.fn();
vi.mock('@/lib/actions/alerts.actions', () => ({
    createAlert: (...args: unknown[]) => createAlert(...args),
    createAlertResult: (...args: unknown[]) => createAlert(...args), deleteAlert: vi.fn(),
    getUserAlertsResult: vi.fn(async () => ({ ok: true, alerts: [] })),
    getTelegramStatus: vi.fn(async () => null), getRecentTriggeredAlerts: vi.fn(async () => []),
}));
vi.mock('@/lib/actions/research.actions', () => ({ reviewResearchExpectations: vi.fn() }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => <input aria-label="Símbolo" /> }));
const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (...a: unknown[]) => toastError(...a), success: vi.fn(), info: vi.fn() } }));
import AlertsManager from '@/components/alerts/AlertsManager';

describe('alta de alerta con umbral ambiguo', () => {
    it('rechaza «1,234» enseñando el formato y sin llamar a la acción', async () => {
        render(<AlertsManager />);
        const crear = await screen.findByRole('button', { name: /^Crear/ });
        fireEvent.click(crear);
        await waitFor(() => expect(toastError).toHaveBeenCalled());
        expect(String(toastError.mock.calls[0][0])).toMatch(/ambiguo/);
        expect(String(toastError.mock.calls[0][0])).toMatch(/1\.234,56/);
        expect(createAlert).not.toHaveBeenCalled();
    });
});
