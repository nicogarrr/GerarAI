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

const text = (markup: string) => markup.replace(/<[^>]*>/g, '|').replace(/\|+/g, '|');

describe('PlanView sin plan configurado', () => {
    // Medido en prod (auditoría 29-oct-2026): sin plan, las cuatro secciones
    // repetían cada una su «sin datos». La página pasa a ser UNA guía de
    // creación y el resto de secciones no se pintan (regla «nada a medias»).
    const renderEmpty = () =>
        text(renderToStaticMarkup(
            <PlanView initialPlan={null} initialContributions={[]} initialDrift={null} />,
        ));

    it('muestra una única guía de creación con su CTA', () => {
        const out = renderEmpty();
        expect(out).toContain('No hay plan de inversión configurado todavía');
        expect(out).toContain('Configurar plan');
    });

    it('no pinta las secciones a medias (posiciones, desviación, aportaciones)', () => {
        const out = renderEmpty();
        expect(out).not.toContain('Posiciones del plan');
        expect(out).not.toContain('Desviación de la cartera');
        expect(out).not.toContain('Aportaciones');
        expect(out).not.toContain('Sin datos de desviación disponibles');
        expect(out).not.toContain('Todavía no has registrado aportaciones');
        expect(out).not.toContain('Objetivo y asignación');
    });

    it('con plan existente sigue pintando todas las secciones', () => {
        const plan = { plan_exists: true, base_currency: 'EUR', monthly_contribution: 300, start_date: '2026-01-01', horizon_years: 25, target_allocations: [] };
        const out = text(renderToStaticMarkup(
            <PlanView initialPlan={plan} initialContributions={[]} initialDrift={null} />,
        ));
        expect(out).toContain('Objetivo y asignación');
        expect(out).toContain('Posiciones del plan');
        expect(out).toContain('Desviación de la cartera');
        expect(out).toContain('Aportaciones');
    });
});
