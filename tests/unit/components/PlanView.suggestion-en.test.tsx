import React from 'react';
import { readFileSync } from 'node:fs';
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
import { LocaleProvider } from '@/lib/i18n/client';

// Frase real de la sugerencia de rebalanceo (investment_plan_service.py,
// leída del .py): «{label} está {x:.1f} puntos por debajo/encima del objetivo».
const PY = readFileSync('data-engine/app/services/investment_plan_service.py', 'utf8');
const detail = (side: 'debajo' | 'encima', label: string, points: number): string => {
    const m = new RegExp(`"detail": f"\\{label\\} (\\S+) \\{float\\([^)]*\\):\\.1f\\} (puntos por ${side} del objetivo)"`).exec(PY);
    if (!m) throw new Error(`no encontrado en investment_plan_service.py: ${side}`);
    return `${label} ${m[1]} ${points.toFixed(1)} ${m[2]}`;
};

const plan = {
    plan_exists: true, base_currency: 'EUR', monthly_contribution: 500, monthly_contribution_currency: 'EUR',
    monthly_currency_recorded: true, currency_contract_enabled: true, expected_basis: 'contract',
    start_date: '2026-01-31', horizon_years: 20, months_elapsed: 9, expected_contributions_base: 4500,
    expected_periods: [], expected_missing_fx: [], actual_contributions_base: 4500,
    actual_contributions_converted_base: 4500, contributions_complete: true, contributions_missing_fx: [],
    gap_base: 0, on_track: true, target_allocations: [],
};
const drift = {
    plan_exists: true, status: 'ok', suggestions_blocked: false, base_currency: 'EUR', portfolio_value_base: 10000, cash_base: 0,
    missing_fx: [], current_weights: {}, deviations: [],
    suggestions: [
        { kind: 'sector', label: 'Technology', direction: 'buy', amount_base: 800, detail: detail('debajo', 'Technology', 8) },
        { kind: 'ticker', label: 'MSFT', direction: 'sell', amount_base: 1250.5, detail: detail('encima', 'MSFT', 12.5) },
    ],
};

const text = (locale: 'es' | 'en') => renderToStaticMarkup(
    <LocaleProvider locale={locale}><PlanView initialPlan={plan} initialContributions={[]} initialDrift={drift} /></LocaleProvider>,
).replace(/<[^>]*>/g, '|').replace(/\|+/g, '|');

describe('PlanView: detalle de las sugerencias en inglés', () => {
    it('la frase de prueba es la del backend', () => {
        expect(drift.suggestions[0].detail).toBe('Technology está 8.0 puntos por debajo del objetivo');
    });
    it('en inglés dice «below/above target», sin el castellano del backend', () => {
        const out = text('en');
        expect(out).toContain('Technology is 8 points below target');
        expect(out).toContain('MSFT is 12.5 points above target');
        expect(out).not.toContain('puntos por');
        expect(out).not.toContain(' está ');
    });
    it('en castellano sigue la frase del backend con la cifra en es-ES', () => {
        const out = text('es');
        expect(out).toContain('Tecnología está 8 puntos por debajo del objetivo');
        expect(out).toContain('MSFT está 12,5 puntos por encima del objetivo');
    });
});
