import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock('@/lib/actions/alerts.actions', () => ({
    createAlert: vi.fn(), createAlertResult: vi.fn(async () => ({ ok: true, alert: {} })), deleteAlert: vi.fn(),
    getUserAlertsResult: vi.fn(async () => ({
        ok: true,
        alerts: [
            { _id: 'a1', symbol: 'MSFT', type: 'price_change', condition: { operator: '>', value: 12.5 }, isActive: true, createdAt: '2026-10-01T10:00:00Z', updatedAt: '2026-10-01T10:00:00Z', channels: ['in_app'], triggerCount: 0 },
            { _id: 'a2', symbol: 'AAPL', type: 'price_above', condition: { operator: '>', value: 1522.6 }, isActive: true, createdAt: '2026-10-01T10:00:00Z', updatedAt: '2026-10-01T10:00:00Z', channels: ['in_app'], triggerCount: 0 },
        ],
    })),
    getTelegramStatus: vi.fn(async () => null), getRecentTriggeredAlerts: vi.fn(async () => []),
}));
vi.mock('@/lib/actions/research.actions', () => ({ reviewResearchExpectations: vi.fn() }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => <input aria-label="Símbolo" /> }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
import AlertsManager from '@/components/alerts/AlertsManager';

describe('etiquetas de alerta en es-ES', () => {
    it('el % de cambio de precio usa coma decimal (no el valor en crudo)', async () => {
        render(<AlertsManager />);
        expect(await screen.findByText(/12,5%/)).toBeInTheDocument();
        expect(document.body.textContent).not.toContain('12.5%');
    });

    it('el umbral de precio agrupa miles y decimal con coma', async () => {
        render(<AlertsManager />);
        expect(await screen.findByText(/1\.522,6/)).toBeInTheDocument();
    });
});
