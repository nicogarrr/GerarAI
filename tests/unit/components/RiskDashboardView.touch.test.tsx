import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const getRiskDashboard = vi.fn();
vi.mock('@/lib/actions/risk.actions', () => ({
    getRiskDashboard: () => getRiskDashboard(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import RiskDashboardView from '@/components/risk/RiskDashboardView';

const base = {
    status: 'ok',
    base_currency: 'EUR',
    total_value: 10000,
    equity_value: 9000,
    top_1_weight: 0.25,
    top_5_weight: 0.8,
    weight_basis: 'gross_equity',
    cash: { EUR: 1000 },
    sector_exposure: { Technology: 0.45 },
    factor_exposure: { growth: 0.5 },
    positions: [
        { ticker: 'ASTS', name: 'AST SpaceMobile', sector: 'Technology', market_value: 2500, weight: 0.25 },
    ],
    alerts: [],
};

describe('RiskDashboardView: objetivos tactiles', () => {
    it('el enlace "Ver cartera" del encabezado es un objetivo tactil de al menos 44px', () => {
        render(<RiskDashboardView initialDashboard={base} />);
        const link = screen.getByRole('link', { name: /Ver cartera/ });
        expect(link.className).toContain('min-h-11');
        expect(link.className).toContain('inline-flex');
        expect(link.className).toContain('items-center');
    });
});
