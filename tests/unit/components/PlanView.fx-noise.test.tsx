import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@/lib/actions/plan.actions', () => ({
    getPlan: vi.fn(), getPlanContributions: vi.fn(), getPlanDrift: vi.fn(),
    addPlanContribution: vi.fn(), deletePlanContribution: vi.fn(), upsertPlan: vi.fn(),
}));
vi.mock('next/link', () => ({ default: ({ href, children, ...rest }: React.ComponentProps<'a'>) => <a href={href} {...rest}>{children}</a> }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh() {}, push() {} }), usePathname: () => '/plan', useSearchParams: () => new URLSearchParams() }));

import PlanView, { planHiddenKeys } from '@/components/plan/PlanView';

const sameCurrency = {
    plan_exists: true, base_currency: 'EUR', monthly_contribution: 300, monthly_contribution_currency: 'EUR',
    start_date: '2026-01-01', horizon_years: 20, months_elapsed: 9,
    expected_contributions_base: 2700, expected_contributions_converted_base: 2700, expected_missing_fx: [], expected_periods: [],
    actual_contributions_base: 2700, actual_contributions_converted_base: 2700, contributions_complete: true, contributions_missing_fx: [],
    gap_base: 0, on_track: true, target_allocations: [],
};

describe('Plan: sin conversiones pendientes no se pintan campos de divisa vacíos', () => {
    it('misma divisa y todo convertido: fuera «convertidas (parcial…)», «cuotas sin tipo…» y «Plan configurado»', () => {
        const html = renderToStaticMarkup(<PlanView initialPlan={sameCurrency} initialContributions={[]} initialDrift={null} />);
        expect(html).toContain('Aportaciones previstas');
        expect(html).not.toContain('parcial si faltan tipos de cambio');
        expect(html).not.toContain('Cuotas sin tipo de cambio');
        expect(html).not.toContain('Cuotas previstas');
        expect(html).not.toContain('Plan configurado');
    });
    it('con una aportación sin tipo de cambio, los campos que lo explican se quedan', () => {
        const missing = { ...sameCurrency, contributions_complete: false, actual_contributions_base: null,
            contributions_missing_fx: [{ id: 4, currency: 'USD', base_currency: 'EUR', as_of: '2026-05-29' }] };
        expect(planHiddenKeys(missing)).not.toContain('contributions_missing_fx');
        expect(planHiddenKeys(missing)).not.toContain('actual_contributions_converted_base');
    });
    it('cuota en otra divisa: se ven las cuotas previstas y sus conversiones', () => {
        const usd = { ...sameCurrency, monthly_contribution_currency: 'USD', expected_periods: [{ period: 1, status: 'converted' }] };
        expect(planHiddenKeys(usd)).not.toContain('expected_periods');
    });
});
