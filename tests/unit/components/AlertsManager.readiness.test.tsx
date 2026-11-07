import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock('@/lib/actions/alerts.actions', () => ({
    createAlertResult: vi.fn(), deleteAlert: vi.fn(),
    getUserAlertsResult: vi.fn(async () => ({ ok: true, alerts: [] })),
    getTelegramStatus: vi.fn(async () => null), getRecentTriggeredAlerts: vi.fn(async () => []),
}));
vi.mock('@/lib/actions/research.actions', () => ({ reviewResearchExpectations: vi.fn() }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => <input aria-label="Símbolo" /> }));
import AlertsManager from '@/components/alerts/AlertsManager';

describe('alert dialog first-click readiness', () => {
    it('renders the trigger disabled before client effects run', () => {
        const html = renderToString(<AlertsManager />);
        const container = document.createElement('div');
        container.innerHTML = html;
        const button = Array.from(container.querySelectorAll('button')).find((item) => item.textContent?.includes('Nueva alerta'));
        expect(button).toBeDefined();
        expect(button).toHaveAttribute('disabled');
    });
    it('enables after mounting and opens all creation controls on one click', async () => {
        render(<AlertsManager />);
        const trigger = screen.getByRole('button', { name: 'Nueva alerta' });
        expect(trigger).toBeDisabled();
        await waitFor(() => expect(trigger).toBeEnabled());
        fireEvent.click(trigger);
        expect(screen.getByRole('dialog')).toBeVisible();
        expect(screen.getByRole('heading', { name: 'Crear alerta' })).toBeVisible();
        expect(screen.getByLabelText('Símbolo')).toBeVisible();
        expect(screen.getByRole('button', { name: 'Crear alerta' })).toBeVisible();
    });
});
