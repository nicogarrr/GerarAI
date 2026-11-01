import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { createTranslator } from '@/lib/i18n/translate';
import { expectationMetricLabel, reviewStatusLabel } from '@/lib/research/expectation-labels';
import { modelConditionState } from '@/lib/research/coverage-state';
import { describeFairValue, describeTrade } from '@/lib/research/journal-trade';

vi.mock('@/lib/actions/research.actions', () => ({
    createResearchDecision: vi.fn(),
    linkResearchDecisionTrade: vi.fn(),
    reviewResearchExpectations: vi.fn(),
}));

const en = createTranslator('en');

describe('diario y expectativas en inglés', () => {
    it('operación y valor justo con formato inglés', () => {
        const trade = { id: 1, trade_date: '2026-03-12', action: 'buy', action_label: 'Compra', quantity: 10, price: 70.5, currency: 'USD' };
        expect(describeTrade(trade, en, 'en')).toBe('Buy 10 @ 70.50 USD · 2026-03-12');
        expect(describeTrade(trade)).toBe('Compra 10 @ 70,50 USD · 12/03/2026');
        expect(describeFairValue(null, en, 'en')).toBe('Fair value that day: no valuation before the trade.');
        const reading = { value: 90, source: 'tesis' as const, version: 1, as_of: '2026-01-10', stale: false, label: 'Thesis v1', margin_vs_trade_price: 0.25, note: null };
        expect(describeFairValue(reading, en, 'en')).toBe('Fair value that day: 90.00 (Thesis v1, 2026-01-10) · margin +25.0%');
    });

    it('estados, métricas y condiciones', () => {
        expect(reviewStatusLabel('pending_actual', en)).toBe('waiting for results');
        expect(reviewStatusLabel('nuevo', en)).toBe('nuevo');
        expect(expectationMetricLabel('fcf_per_share', en)).toBe('FCF per share');
        expect(expectationMetricLabel('metrica_nueva', en)).toBe('metrica nueva');
        expect(modelConditionState({ id: 'roic_above_wacc', value: 0.1, comparison: null, status: 'ok' }, true, en)).toBe('Pending: no WACC data');
        expect(modelConditionState({ id: 'roic_above_wacc', value: 0.1, comparison: null, status: 'ok' }, true)).toBe('Pendiente: WACC sin datos');
    });

    it('el panel del diario se pinta en inglés', async () => {
        const { DecisionAndRealityPanel, journalVersionLabel } = await import('@/components/research/FundamentalModelPanels');
        expect(journalVersionLabel({ thesis_version_id: 7, model_version_id: null, metadata: { thesis_version: 3 } }, en)).toBe('Against thesis v3 · no model');
        const html = renderToStaticMarkup(<DecisionAndRealityPanel ticker="AAPL" decisions={[]} reviews={[]} t={en} locale="en" />);
        expect(html).toContain('Decision journal');
        expect(html).toContain('Record decision');
        expect(html).toContain('Expectations vs reality');
        expect(html).not.toContain('Diario de decisiones');
    });
});
