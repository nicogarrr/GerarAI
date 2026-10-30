import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/actions/plan.actions', () => ({
    getPlan: vi.fn(), getPlanContributions: vi.fn(), getPlanDrift: vi.fn(),
    addPlanContribution: vi.fn(), deletePlanContribution: vi.fn(), upsertPlan: vi.fn(),
}));
vi.mock('next/link', () => ({ default: ({ href, children, ...rest }: React.ComponentProps<'a'>) => <a href={href} {...rest}>{children}</a> }));
vi.mock('next/navigation', () => ({
    useRouter: () => ({ refresh() {}, push() {} }),
    usePathname: () => '/plan',
    useSearchParams: () => new URLSearchParams(),
}));

import PlanView from '@/components/plan/PlanView';
import { contributionFormError } from '@/components/plan/PlanContributionDialog';

const plan = { plan_exists: true, base_currency: 'EUR', monthly_contribution: 300, monthly_contribution_currency: 'EUR', start_date: '2026-01-01', horizon_years: 20, target_allocations: [] };
const text = (contributions: Record<string, unknown>[]) => renderToStaticMarkup(
    <PlanView initialPlan={plan} initialContributions={contributions} initialDrift={null} />,
);

describe('Plan: registrar y borrar aportaciones desde la UI', () => {
    it('sin aportaciones, el estado vacío ofrece «Registrar aportación»', () => {
        expect(text([])).toContain('Registrar aportación');
    });
    it('con aportaciones, cada fila se puede eliminar y sigue habiendo alta', () => {
        const html = text([{ id: 3, date: '2026-04-30', amount: 300, currency: 'EUR', note: '' }]);
        expect(html).toContain('Eliminar aportación: 30 abr 2026');
        expect(html).toContain('Registrar aportación');
    });
    it('tras router.refresh() la lista pinta la aportación nueva (no se queda con el estado inicial)', () => {
        const first = [{ id: 3, date: '2026-04-30', amount: 300, currency: 'EUR', note: '' }];
        const { rerender } = render(<PlanView initialPlan={plan} initialContributions={first} initialDrift={null} />);
        expect(screen.queryAllByText('prueba nueva')).toHaveLength(0);
        rerender(<PlanView initialPlan={plan} initialContributions={[...first, { id: 4, date: '2026-05-29', amount: 50, currency: 'EUR', note: 'prueba nueva' }]} initialDrift={null} />);
        expect(screen.getAllByText('prueba nueva').length).toBeGreaterThan(0);
    });
    it('valida fecha, importe y fecha futura en es-ES', () => {
        const today = '2026-10-30';
        expect(contributionFormError({ date: '2026-10-01', amount: 300, today })).toBeNull();
        expect(contributionFormError({ date: '', amount: 300, today })).toMatch(/fecha/);
        expect(contributionFormError({ date: '2026-11-01', amount: 300, today })).toMatch(/futura/);
        expect(contributionFormError({ date: '2026-10-01', amount: 0, today })).toMatch(/mayor que 0/);
        expect(contributionFormError({ date: '2026-10-01', amount: null, today })).toMatch(/mayor que 0/);
        expect(contributionFormError({ date: '2026-10-01', amount: 20_000_000, today })).toMatch(/superar/);
    });
});
