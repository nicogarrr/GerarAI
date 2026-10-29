import axe from 'axe-core';
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// axe heading-order en /plan, /propicks, /risk, /corporate-actions y
// /knowledge (Cerebro embebido): CardTitle es h3 por defecto y estas pantallas
// saltaban del h1 de la página a h3 (visto con axe en build de producción,
// ronda 3). Ahora son h2.

vi.mock('next/navigation', () => ({
    useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
    useSearchParams: () => new URLSearchParams(),
    usePathname: () => '/plan',
}));
vi.mock('@/lib/actions/plan.actions', () => ({ getPlan: vi.fn(), getPlanContributions: vi.fn(), getPlanDrift: vi.fn() }));
vi.mock('@/lib/actions/risk.actions', () => ({ getRiskDashboard: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
vi.mock('@/lib/actions/corporate-actions.actions', () => ({ getCorporateActions: vi.fn(async () => []) }));
vi.mock('@/components/plan/PlanSetupDialog', () => ({ default: () => null }));

import PlanView from '@/components/plan/PlanView';
import CorporateActionsView from '@/components/corporate-actions/CorporateActionsView';
import RiskDashboardView from '@/components/risk/RiskDashboardView';

async function headingOrder(node: Element) {
    const result = await axe.run(node, { runOnly: { type: 'rule', values: ['heading-order'] } });
    return result.violations.flatMap((v) => v.nodes.map((n) => n.html));
}
const levels = (node: Element) =>
    Array.from(node.querySelectorAll('h1,h2,h3,h4,h5,h6')).map((h) => `${h.tagName.toLowerCase()} ${h.textContent?.trim()}`);

describe('a11y: sin saltos h1 -> h3 (heading-order)', () => {
    it('/plan: las tarjetas son h2 bajo el h1', async () => {
        const { container } = render(
            <main>
                <h1>Plan de inversión</h1>
                <PlanView initialPlan={{ plan_exists: true } as never} initialContributions={[]} initialDrift={null} />
            </main>,
        );
        const found = levels(container);
        expect(found).toContain('h2 Objetivo y asignación');
        expect(found).toContain('h2 Posiciones del plan');
        expect(found).not.toContain('h3 Objetivo y asignación');
        expect(await headingOrder(container)).toEqual([]);
    });

    it('/corporate-actions: el título oculto de la tabla es h2', async () => {
        const { container } = render(
            <main>
                <h1>Acciones corporativas</h1>
                <CorporateActionsView initialActions={[]} />
            </main>,
        );
        expect(levels(container)).toContain('h2 Acciones corporativas');
        expect(await headingOrder(container)).toEqual([]);
    });

    it('/risk: alertas y exposición por posición son h2', async () => {
        const { container } = render(
            <main>
                <h1>Exposiciones de cartera</h1>
                <RiskDashboardView initialDashboard={null} />
            </main>,
        );
        const found = levels(container);
        expect(found.some((h) => h.startsWith('h3'))).toBe(false);
        expect(await headingOrder(container)).toEqual([]);
    });
});
