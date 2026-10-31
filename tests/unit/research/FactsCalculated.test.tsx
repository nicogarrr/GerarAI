import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { FactCard, FactTable } from '@/components/research/FactsPanels';
import type { ResearchFact } from '@/lib/actions/research.actions';

const baseFact: ResearchFact = {
    id: 1,
    company_id: 1,
    metric: 'revenue',
    value: '245122000000',
    unit: 'USD',
    period: 'FY2025',
    fiscal_year: 2025,
    fiscal_quarter: null,
    source_id: null,
    source_type: 'ESEF',
    is_reported: true,
    is_adjusted: false,
    confidence: 'high',
    created_at: '2026-01-01T00:00:00Z',
    source_url: null,
    source_title: null,
    source_published_at: null,
};

const derivedFact: ResearchFact = { ...baseFact, id: 2, is_reported: false };

describe('Hechos derivados conservan la marca «Calculado» (no es etiqueta de fuente)', () => {
    it('FactCard: un hecho con is_reported=false muestra «Calculado» junto al valor', () => {
        const html = renderToStaticMarkup(<FactCard fact={derivedFact} ticker="MSFT" staleness={null} />);
        expect(html).toContain('Calculado');
    });
    it('FactCard: un hecho reportado no muestra «Calculado»', () => {
        const html = renderToStaticMarkup(<FactCard fact={baseFact} ticker="MSFT" staleness={null} />);
        expect(html).not.toContain('Calculado');
    });
    it('FactTable: con solo hechos derivados aparece «Calculado» junto al valor (cards y tabla)', () => {
        const html = renderToStaticMarkup(<FactTable facts={[derivedFact]} refreshLabel="Actualizar" ticker="MSFT" />);
        expect(html).toContain('Calculado');
    });
    it('FactTable: con solo hechos reportados no aparece «Calculado»', () => {
        const html = renderToStaticMarkup(<FactTable facts={[baseFact]} refreshLabel="Actualizar" ticker="MSFT" />);
        expect(html).not.toContain('Calculado');
    });
});
