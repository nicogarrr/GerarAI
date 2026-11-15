import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/research-tools.actions', () => ({
    createManagementPromiseResult: vi.fn(), importManagementCallClaims: vi.fn(),
    reconcileManagementCredibility: vi.fn(), updateManagementExplanationResult: vi.fn(),
    getManagementCredibility: vi.fn(), getDriverAssumptions: vi.fn(), getDecisionLessons: vi.fn(),
    createDriverAssumptionResult: vi.fn(),
}));

import { DriverAssumptionsSection, type DriverAssumptions } from '@/components/research/sections/DriverAssumptionsSection';
import { ManagementCredibilitySection, type ManagementCredibility } from '@/components/research/sections/ManagementCredibilitySection';
import { driverLabel } from '@/lib/research/driver-label';

const dashboard = {
    score: 0.67, grade: 'mixed', method: 'resolved promises: met=1, partial=0.5, missed=0',
    counts: { total: 7, open: 2, met: 3, partial: 1, missed: 1 },
    promises: [{ id: 1, status: 'met', promise_date: '2025-11-05', expected_period: 'FY2026', promise: 'Margen > 30 %', metric: 'operating_margin', operator: '>', target_value: 0.3, unit: null, actual_value: 0.32, management_explanation: null, verified_at: '2026-10-30', evidence: [] }],
} as unknown as ManagementCredibility;

const assumptions = [
    { id: 7, driver_id: 1, driver_key: 'revenue_growth', fiscal_year: 2027, scenario: 'base', value: 0.18, source: 'guía', user_override: true, confidence: 0.8, rationale: 'r', previous_version_id: null, created_at: '2026-10-01T00:00:00Z' },
    { id: 9, driver_id: 3, driver_key: 'fleet_utilization', fiscal_year: 2028, scenario: 'bull', value: 0.74, source: 'ajuste', user_override: true, confidence: 0.4, rationale: 'r', previous_version_id: null, created_at: '2026-10-02T00:00:00Z' },
] as unknown as DriverAssumptions;

describe('credibilidad de la directiva legible', () => {
    it('explica qué mide la puntuación 0-100 junto a la cifra', () => {
        const html = renderToStaticMarkup(<ManagementCredibilitySection dashboard={dashboard} ticker="UBER" />);
        expect(html).toContain('data-testid="management-score-explainer"');
        expect(html).toContain('solo pesan las promesas ya resueltas');
        expect(html).toContain('las abiertas no cuentan');
        const en = renderToStaticMarkup(<ManagementCredibilitySection dashboard={dashboard} locale="en" ticker="UBER" />);
        expect(en).toContain('only resolved promises count');
    });
});

describe('supuestos del modelo legibles', () => {
    it('traduce las driver_key conocidas y deja las desconocidas legibles sin inventar', () => {
        expect(driverLabel('revenue_growth', 'es')).toBe('crecimiento de ingresos');
        expect(driverLabel('wacc', 'es')).toBe('WACC');
        expect(driverLabel('fleet_utilization', 'es')).toBe('fleet utilization');
        expect(driverLabel('revenue_growth', 'en')).toBe('revenue growth');
    });
    it('muestra la etiqueta legible conservando la clave cruda, y la leyenda de confianza', () => {
        const html = renderToStaticMarkup(<DriverAssumptionsSection assumptions={assumptions} ticker="UBER" />);
        expect(html).toContain('crecimiento de ingresos');
        expect(html).toContain('title="revenue_growth"');
        expect(html).toContain('fleet utilization');
        expect(html).toContain('data-testid="driver-confidence-legend"');
        expect(html).toContain('no un dato reportado');
        const en = renderToStaticMarkup(<DriverAssumptionsSection assumptions={assumptions} locale="en" ticker="UBER" />);
        expect(en).toContain('judgment, not reported data');
    });
});

it('keeps driver fallback scenarios, versions and empty history honest', () => {
    const rows = ['', 'bear', 'custom_case', 'bull'].map((scenario, index) => ({
        ...assumptions[0], id: index + 20, scenario, previous_version_id: 7,
    }));
    const html = renderToStaticMarkup(<DriverAssumptionsSection ticker="UBER" assumptions={rows as DriverAssumptions} />);
    expect(html).toContain('custom case');
    expect(html).toContain('← #7');
    expect(html).toContain('—');
    expect(renderToStaticMarkup(<DriverAssumptionsSection ticker="UBER" assumptions={[]} />)).toContain('driver-confidence-legend');
});

it('keeps unknown management states and qualitative missing fields visible', () => {
    const partial = { ...dashboard, grade: 'custom_grade', method: 'custom_method', promises: [
        {...dashboard.promises[0], status: '', metric: null, actual_value: null, verified_at: null, management_explanation: 'Explanation'},
        {...dashboard.promises[0], id: 2, status: 'custom_state', target_value: null},
    ] } as ManagementCredibility;
    const html = renderToStaticMarkup(<ManagementCredibilitySection ticker="UBER" dashboard={partial} />);
    expect(html).toContain('custom state');
    expect(html).toContain('Explanation');
    expect(html).toContain('custom_grade');
});
