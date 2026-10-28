import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Agente persona «caos» (qa-agents, 28/10): un símbolo de 500+ caracteres y
// precio 999999999 llegaban a la server action createAlert, que lanza
// ValidationError -> POST /alerts 500 (en producción, error genérico).
const LONG = 'A'.repeat(500);
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(`symbol=${LONG}&type=price_above&value=999999999`) }));
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

describe('alta de alerta con símbolo inválido', () => {
    it('no llama a la server action y avisa en español', async () => {
        render(<AlertsManager />);
        const crear = await screen.findByRole('button', { name: /^Crear/ });
        fireEvent.click(crear);
        await waitFor(() => expect(toastError).toHaveBeenCalled());
        expect(createAlert).not.toHaveBeenCalled();
        expect(String(toastError.mock.calls[0][0])).toMatch(/símbolo válido/);
    });
});
