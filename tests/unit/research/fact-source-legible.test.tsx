/**
 * El proveedor de un hecho y la fuente de la evidencia de valoración se
 * pintaban con el id interno del backend en crudo («YAHOO_FUNDAMENTALS»,
 * «sec»), pese a existir sourceDisplay() con etiquetas es/en. Regresión:
 * ids conocidos traducidos, desconocidos humanizados, nunca el crudo.
 */
import { readFileSync } from 'node:fs';
import { renderToString } from 'react-dom/server';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FactSource } from '@/components/research/FactSource';
import { ValuationSummaryCard } from '@/components/research/ValuationSummaryGrid';
import type { ResearchFact } from '@/lib/actions/research.actions';
import type { ValuationSummary } from '@/lib/research/valuation-summary';

const item: ValuationSummary = {
    ticker: 'DEMO',
    fair_value: { value: 100, currency: 'USD', label: 'Motor de valoración', as_of: '2026-10-29', publishable: true, stale: false },
    reverse_dcf: { status: 'ok', required_revenue_growth: 0.08, as_of: '2026-10-29', source: 'Modelo persistido', market_price: 80, model_version_id: 1 },
    health: {
        status: 'not_evaluable', notice: 'Indicadores contables.', period_end: '2025-12-31',
        piotroski: {
            score: null, evaluated: 1, total: 9, methodology_url: 'https://example.com/p',
            signals: [{ id: 'roa', label: 'Rentabilidad positiva', formula: 'NI / A > 0', point: 1, missing_input: null, evidence: [{ fact_id: 4, metric: 'net_income', value: 10, unit: 'USD', period_end: '2025-12-31', source_type: 'yahoo_fundamentals', source_url: 'https://example.com/e' }] }],
        },
        altman: { score: null, status: 'not_evaluable', variant: 'Z_double_prime', reason: undefined, methodology_url: 'https://example.com/a' },
    },
};
const quote = { symbol: 'DEMO', price: 80, currency: 'USD' };

const fact = (sourceType: string): ResearchFact => ({
    id: 1, company_id: 1, metric: 'revenue', value: '1000000', unit: 'USD', period: 'FY2025',
    fiscal_year: 2025, fiscal_quarter: null, source_id: 1, source_type: sourceType,
    is_reported: true, is_adjusted: false, confidence: 'high', created_at: '2026-11-11T00:00:00Z',
    source_title: null, source_url: null, source_published_at: null,
});

describe('FactSource: proveedor legible', () => {
    it('es: id conocido traducido', () => {
        const html = renderToString(<FactSource fact={fact('YAHOO_FUNDAMENTALS')} locale="es" />);
        expect(html).toContain('Yahoo Finance (fuente no oficial)');
        expect(html).not.toContain('YAHOO_FUNDAMENTALS');
    });
    it('en: id conocido traducido al inglés', () => {
        const html = renderToString(<FactSource fact={fact('yahoo_finance')} locale="en" />);
        expect(html).toContain('Yahoo Finance');
    });
    it('id desconocido: humanizado, nunca el crudo con guiones bajos', () => {
        const html = renderToString(<FactSource fact={fact('proprietary_feed')} locale="es" />);
        expect(html).toContain('proprietary feed');
        expect(html).not.toContain('proprietary_feed');
    });
});

describe('ValuationSummaryCard: fuente de la evidencia legible', () => {
    it('traduce el id de fuente y no muestra el crudo', () => {
        render(<ValuationSummaryCard item={item} quote={quote} />);
        expect(screen.getAllByText(/Yahoo Finance \(fuente no oficial\)/).length).toBeGreaterThan(0);
        expect(screen.queryByText(/yahoo_fundamentals/)).toBeNull();
    });
});

describe('los componentes dejan de pintar el id crudo', () => {
    it('FactSource usa sourceDisplay', () => {
        const source = readFileSync('components/research/FactSource.tsx', 'utf8');
        expect(source).toContain('sourceDisplay(');
    });
    it('ValuationSummaryGrid usa sourceDisplay para la evidencia', () => {
        const source = readFileSync('components/research/ValuationSummaryGrid.tsx', 'utf8');
        expect(source).toContain('sourceDisplay(');
        expect(source).not.toContain('{f.source_type}');
    });
});
