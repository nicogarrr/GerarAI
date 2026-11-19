import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@/lib/actions/plan.actions', () => ({
    getPlan: vi.fn(), getPlanContributions: vi.fn(), getPlanDrift: vi.fn(),
    addPlanContribution: vi.fn(), deletePlanContribution: vi.fn(), upsertPlan: vi.fn(),
}));
vi.mock('next/link', () => ({ default: ({ href, children, ...rest }: React.ComponentProps<'a'>) => <a href={href} {...rest}>{children}</a> }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh() {}, push() {} }), usePathname: () => '/plan', useSearchParams: () => new URLSearchParams() }));

import PlanView from '@/components/plan/PlanView';
import { LocaleProvider } from '@/lib/i18n/client';

/** Plan con la cuota en USD sin registrar y FX pendientes por todas partes. */
const fxPlan = {
    plan_exists: true, base_currency: 'EUR', monthly_contribution: 300,
    currency_contract_enabled: true, monthly_currency_recorded: false,
    start_date: '2026-01-01', horizon_years: 20, months_elapsed: 9,
    expected_contributions_base: 2700, gap_base: 0, on_track: true,
    target_allocations: [{ kind: 'ticker', label: 'UBER', target_pct: 50 }],
    expected_periods: [],
    expected_missing_fx: [
        { quote_currency: 'usd', base_currency: 'EUR', due_date: '2026-03-01' },
        { quote_currency: 'usd', base_currency: 'EUR', due_date: '2026-04-01' },
    ],
    contributions_missing_fx: [
        { quote_currency: 'usd', base_currency: 'eur', as_of: '2026-01-31' },
        { quote_currency: 'usd', base_currency: 'eur', as_of: '2026-02-27' },
        { quote_currency: 'gbp', base_currency: 'eur', as_of: '2026-03-31' },
        { quote_currency: 'usd', base_currency: 'eur', as_of: '2026-04-30' },
    ],
};

const drift = {
    plan_exists: true, status: 'incomplete_fx',
    portfolio_value_base: 10000, cash_base: 500, base_currency: 'EUR',
    current_weights: { 'ticker:POOL': 0.52, 'asset_class:Cash': 0.1, 'sector:Technology': 0.4 },
    deviations: [
        { kind: 'ticker', label: 'POOL', detail: 'POOL está 2.50 puntos por debajo del objetivo', direction: 'buy', current_pct: 48, target_pct: 50, deviation_pct: -2.5, within_band: false },
    ],
    suggestions: [
        { kind: 'ticker', label: 'POOL', action: 'buy', amount_base: 25, detail: 'POOL está 2.50 puntos por debajo del objetivo' },
        { kind: 'sector', label: 'Technology', action: 'sell', amount_base: 10, detail: 'Technology está 3.25 puntos por encima del objetivo' },
    ],
    missing_fx: [
        { kind: 'cash', quote_currency: 'USD', base_currency: 'EUR', as_of: '2026-10-01' },
        { kind: 'position', ticker: 'POOL', quote_currency: 'USD', base_currency: 'EUR', as_of: '2026-10-02' },
        { kind: 'otra_clase', ticker: 'X', quote_currency: 'USD', base_currency: 'EUR', as_of: null },
    ],
    next_contribution: 300, next_contribution_currency: 'USD',
};

describe('PlanView: resúmenes de divisa y detalle del drift', () => {
    it('contrato activo sin divisa registrada: cuota cruda y cuotas no calculables', () => {
        const html = renderToStaticMarkup(<PlanView initialPlan={fxPlan} initialContributions={[]} initialDrift={null} />);
        expect(html).toContain('(divisa no registrada)');
    });

    it('cuotas previstas: convertidas, pendientes de vencimiento y sin tipo de cambio', () => {
        const plan = {
            ...fxPlan, monthly_currency_recorded: true, monthly_contribution_currency: 'USD',
            expected_periods: [
                { period: 1, status: 'converted' },
                { period: 2, status: 'pending_due_date' },
                { period: 3, status: 'missing_rate' },
            ],
        };
        const html = renderToStaticMarkup(<PlanView initialPlan={plan} initialContributions={[]} initialDrift={null} />);
        expect(html).toContain('1 convertidas');
        expect(html).toContain('1 pendientes de vencimiento');
        expect(html).toContain('1 sin tipo de cambio');
        // Cuota registrada en USD: se pinta en su divisa.
        expect(html).toContain('300,00');
    });

    it('cuotas vencidas sin tipo: pares y rango de vencimiento legibles', () => {
        const plan = { ...fxPlan, monthly_currency_recorded: true, monthly_contribution_currency: 'USD' };
        const html = renderToStaticMarkup(<PlanView initialPlan={plan} initialContributions={[]} initialDrift={null} />);
        expect(html).toContain('2 cuotas sin tipo de cambio usd→EUR');
        expect(html).toContain('vencidas del');
    });

    it('aportaciones sin tipo: pares únicos y «y N más» pasadas tres fechas', () => {
        const plan = { ...fxPlan, monthly_currency_recorded: true, monthly_contribution_currency: 'USD', expected_missing_fx: [] };
        const html = renderToStaticMarkup(<PlanView initialPlan={plan} initialContributions={[]} initialDrift={null} />);
        expect(html).toContain('4 aportaciones sin tipo de cambio USD→EUR, GBP→EUR');
        expect(html).toContain('y 1 más');
    });

    it('drift: pesos por ticker enlazan a research, detalle y kind se traducen', () => {
        const plan = { ...fxPlan, monthly_currency_recorded: true, monthly_contribution_currency: 'USD', expected_missing_fx: [], contributions_missing_fx: [] };
        const html = renderToStaticMarkup(<PlanView initialPlan={plan} initialContributions={[]} initialDrift={drift} />);
        // Chips de posiciones: de los pesos del drift y de los objetivos del plan.
        expect(html).toContain('/research/POOL');
        expect(html).toContain('/research/UBER');
        // Cabeceras traducidas y detalle con la etiqueta localizada.
        expect(html).toContain('Tecnología está');
        expect(html).toContain('Faltan tipos de cambio');
        expect(html).toContain('Comprar');
        expect(html).toContain('Vender');
        // kind cash/position del missing_fx ya no salen en inglés; el desconocido pasa tal cual.
        expect(html).toContain('Caja');
        expect(html).toContain('otra_clase');
        // Próxima aportación en SU divisa registrada.
        expect(html).toContain('300,00');
    });

    it('en inglés el detalle castellano del backend se reescribe con la plantilla', () => {
        const plan = { ...fxPlan, monthly_currency_recorded: true, monthly_contribution_currency: 'USD', expected_missing_fx: [], contributions_missing_fx: [] };
        const html = renderToStaticMarkup(
            <LocaleProvider locale="en">
                <PlanView initialPlan={plan} initialContributions={[]} initialDrift={drift} />
            </LocaleProvider>,
        );
        expect(html).toContain('below target');
        expect(html).toContain('above target');
    });
});
