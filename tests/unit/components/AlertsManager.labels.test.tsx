import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams('symbol=MSFT&type=price_change&value=5') }));
vi.mock('@/lib/actions/alerts.actions', () => ({
    createAlert: vi.fn(), createAlertResult: vi.fn(async () => ({ ok: true, alert: {} })), deleteAlert: vi.fn(),
    getUserAlertsResult: vi.fn(async () => ({ ok: true, alerts: [] })),
    getTelegramStatus: vi.fn(async () => null), getRecentTriggeredAlerts: vi.fn(async () => []),
}));
vi.mock('@/lib/actions/research.actions', () => ({ reviewResearchExpectations: vi.fn() }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => <input aria-label="Símbolo" /> }));
import AlertsManager from '@/components/alerts/AlertsManager';

describe('Alert creation selector labels', () => {
    it('exposes the alert type selector by its visible label', async () => {
        render(<AlertsManager />);
        await waitFor(() => expect(screen.getByRole('combobox', { name: 'Tipo de Alerta' })).toBeInTheDocument());
        expect(screen.getByRole('combobox', { name: 'Tipo de Alerta' })).toHaveAttribute('id', 'type');
    });
    it('exposes the operator selector by its visible label for percentage alerts', async () => {
        render(<AlertsManager />);
        await waitFor(() => expect(screen.getByRole('combobox', { name: 'Operador' })).toBeInTheDocument());
        expect(screen.getByRole('combobox', { name: 'Operador' })).toHaveAttribute('id', 'operator');
    });
});
