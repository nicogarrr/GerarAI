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

// Plan legacy (sin divisa registrada) tal como lo devuelve GET /api/plan.
const plan = {
    plan_exists: true, base_currency: 'EUR', monthly_contribution: 500, monthly_contribution_currency: null,
    monthly_currency_recorded: false, currency_contract_enabled: false, expected_basis: 'legacy_monthly_as_base',
    start_date: '2026-01-31', horizon_years: 20, months_elapsed: 9, expected_contributions_base: 4000,
    expected_periods: [], expected_missing_fx: [], actual_contributions_base: null,
    actual_contributions_converted_base: 1500, contributions_complete: false,
    contributions_missing_fx: [{ contribution_id: 4, quote_currency: 'USD', base_currency: 'EUR', as_of: '2026-05-29' }],
    gap_base: null, on_track: null, target_allocations: [],
};
const drift = {
    plan_exists: true, status: 'ok', suggestions_blocked: false, base_currency: 'EUR', portfolio_value_base: 1000, cash_base: 0,
    missing_fx: [], current_weights: {},
    deviations: [],
    suggestions: [
        { kind: 'ticker', label: 'MSFT', direction: 'buy', amount_base: 500, detail: 'MSFT está 50.0 puntos por debajo del objetivo' },
        { kind: 'sector', label: 'Technology', direction: 'buy', amount_base: 800, detail: 'Technology está 80.0 puntos por debajo del objetivo' },
    ],
};
const contributions = [{ id: 3, date: '2026-04-30', amount: 500, currency: 'eur', note: '' }];

const text = () => renderToStaticMarkup(
    <PlanView initialPlan={plan} initialContributions={contributions} initialDrift={drift} />,
).replace(/<[^>]*>/g, '|').replace(/\|+/g, '|');

describe('PlanView: lectura del plan en es-ES', () => {
    it('las aportaciones sin tipo de cambio se resumen sin claves crudas', () => {
        const out = text();
        expect(out).not.toContain('contribution id');
        expect(out).not.toContain('quote currency');
        expect(out).toContain('1 aportación sin tipo de cambio USD→EUR (29 may 2026)');
    });
    it('un plan sin divisa registrada no presume «0 convertidas, 0 pendientes»', () => {
        expect(text()).not.toContain('0 convertidas');
    });
    it('la sugerencia dice «Operación: Comprar», no «Acción: Comprar» bajo «Acción: MSFT»', () => {
        const out = text();
        expect(out).toContain('Operación: Comprar');
        expect(out).not.toContain('Acción: Comprar');
    });
    it('el detalle de una sugerencia por sector traduce el sector', () => {
        const out = text();
        expect(out).toContain('Tecnología está 80 puntos por debajo del objetivo');
        expect(out).not.toContain('Technology');
    });
    it('el historial de aportaciones muestra la fecha en es-ES y la divisa en mayúsculas', () => {
        const out = text();
        expect(out).toContain('30 abr 2026');
        expect(out).not.toContain('2026-04-30');
        expect(out).not.toContain('|eur|');
    });
});
