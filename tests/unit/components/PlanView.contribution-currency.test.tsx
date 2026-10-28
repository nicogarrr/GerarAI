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

const basePlan = { plan_exists: true, base_currency: 'EUR', monthly_contribution: 500, start_date: '2026-01-01', horizon_years: 10, target_allocations: [] };

/** Texto visible del render, sin etiquetas. */
const render = (plan: Record<string, unknown>, drift: Record<string, unknown> = {}) =>
    renderToStaticMarkup(<PlanView initialPlan={plan} initialContributions={[]} initialDrift={drift} />)
        .replace(/<[^>]*>/g, '|').replace(/\|+/g, '|');

describe('PlanView: aportación mensual y divisa', () => {
    it('plan legacy sin divisa (contrato apagado): importe crudo, sin € inventado', () => {
        const text = render({ ...basePlan, monthly_contribution_currency: null, monthly_currency_recorded: false, currency_contract_enabled: false });
        expect(text).toContain('Aportación mensual|500 (divisa no registrada)');
        expect(text).not.toContain('500,00');
    });
    it('divisa registrada: se formatea con su divisa', () => {
        const text = render({ ...basePlan, monthly_contribution_currency: 'EUR', monthly_currency_recorded: true, currency_contract_enabled: false });
        expect(text).toMatch(/Aportación mensual\|500,00\s€/);
    });
    it('payload sin flag (fallback existente): EUR como antes', () => {
        const text = render({ ...basePlan, base_currency: null });
        expect(text).toMatch(/Aportación mensual\|500,00\s€/);
    });
});
