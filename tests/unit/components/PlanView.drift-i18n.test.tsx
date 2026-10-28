import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@/lib/actions/plan.actions', () => ({ getPlan: vi.fn(), getPlanContributions: vi.fn(), getPlanDrift: vi.fn() }));
vi.mock('next/link', () => ({ default: ({ href, children, ...rest }: React.ComponentProps<'a'>) => <a href={href} {...rest}>{children}</a> }));
vi.mock('next/navigation', () => ({
    useRouter: () => ({ refresh() {}, push() {} }),
    usePathname: () => '/plan',
    useSearchParams: () => new URLSearchParams(),
}));

import PlanView from '@/components/plan/PlanView';

const basePlan = { plan_exists: true, base_currency: 'EUR', monthly_contribution: 300, start_date: '2026-01-01', horizon_years: 25, target_allocations: [] };

const render = (drift: Record<string, unknown>) =>
    renderToStaticMarkup(<PlanView initialPlan={basePlan} initialContributions={[]} initialDrift={drift} />)
        .replace(/<[^>]*>/g, '|').replace(/\|+/g, '|');

const drift = {
    plan_exists: true,
    status: 'incomplete_fx',
    suggestions_blocked: true,
    base_currency: 'EUR',
    portfolio_value_base: 0,
    cash_base: 0,
    missing_fx: [
        { kind: 'position', ticker: 'AAPL', quote_currency: 'USD', base_currency: 'EUR', as_of: '2026-01-15' },
        { kind: 'cash', quote_currency: 'USD', base_currency: 'EUR', as_of: '2026-03-10' },
    ],
    current_weights: [],
    deviations: [
        { kind: 'ticker', label: 'AAPL', target_pct: 40, band_pct: 5, current_pct: 0, deviation_pct: -40, within_band: false },
        { kind: 'asset_class', label: 'Cash', target_pct: 25, band_pct: 5, current_pct: 0, deviation_pct: -25, within_band: false },
    ],
    suggestions: null,
};

describe('PlanView: missing_fx y Cash en es-ES', () => {
    it('las filas sin tipo de cambio no muestran claves ni valores en inglés', () => {
        const text = render(drift);
        expect(text).toContain('Divisa de cotización');
        expect(text).toContain('Divisa base');
        expect(text).toContain('Posición');
        expect(text).toContain('Fecha');
        expect(text).toContain('15 ene 2026');
        expect(text).not.toContain('quote currency');
        expect(text).not.toContain('base currency');
        expect(text).not.toContain('as of');
        expect(text).not.toContain('position');
    });
    it('asset_class Cash se lee «Caja», no «Cash»', () => {
        const text = render(drift);
        expect(text).toContain('Clase de activo: Caja');
        expect(text).not.toContain('Cash');
    });
});
