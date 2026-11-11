import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/components/research/ThesisHumanInputForm', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisInvalidationRulesForm', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisDebatePanel', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisMarkdownPager', () => ({ default: () => null }));
vi.mock('@/components/GlossaryTerm', () => ({ GlossaryTerm: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
import ThesisMemo from '@/components/research/ThesisMemo';
import type { ResearchThesis } from '@/lib/actions/research.actions';

// Auditoría fa-tesis (r5): en la pestaña Tesis la valoración (precio del
// modelo, bear/base/bull, valor esperado y margen) salía DESPUÉS de la tabla
// de procedencia de inputs y de la narrativa larga: en un iPhone, varias
// pantallas de scroll antes de ver si la acción está cara o barata.
const thesis = {
  id: 1, company_id: 1, version: 8, status: 'published', rating: 'expensive',
  thesis_markdown: '# POOL', executive_summary: 'Distribuidor líder de piscinas; el precio descuenta más de lo que el negocio da hoy.',
  hypothesis: 'La demanda de mantenimiento sostiene márgenes aunque caiga la obra nueva.',
  current_price: '211.70', bear_value: '98.10', base_value: '137.51', bull_value: '190.20', expected_value: '140.00',
  margin_of_safety: '-0.5395', valuation_basis: { margin_of_safety_convention: 'discount_to_value_v1' },
  data_confidence_score: 80, source_coverage_score: 80, red_team_score: 80, valuation_risk_score: 30,
  created_at: '2026-11-08T06:54:00Z',
  inputs_provenance: [
    { key: 'revenue', label: 'dato', value: 5300, unit: 'USD', origen: 'OFICIAL', fuentes: [{ fact_id: 1, url: 'https://www.sec.gov/x', fecha: '2026-02-20', titulo: '10-K', oficial: true }] },
    { key: 'fcf_margin', label: 'derivado', value: 0.08, unit: 'ratio' },
  ],
  narrative_sections: [{ titulo: 'Negocio', parrafos: ['Párrafo largo de la narrativa.'] }],
} as unknown as ResearchThesis;

const before = (a: HTMLElement, b: HTMLElement) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe('ThesisMemo · conclusión primero', () => {
  it('resumen y «Escenarios y valoración» van antes que la procedencia y la narrativa', () => {
    render(<ThesisMemo thesis={thesis} currency="USD" model={{ publishable: true }} />);
    const summary = screen.getByText(/Distribuidor líder de piscinas/);
    const scenarios = screen.getByText('Escenarios y valoración');
    const margin = screen.getByText('Margen de seguridad');
    const provenance = screen.getByText('Procedencia de los inputs');
    const narrative = screen.getByRole('region', { name: 'Análisis narrativo' });
    const hypothesis = screen.getByText('Hipótesis');
    expect(before(summary, scenarios)).toBe(true);
    expect(before(margin, provenance)).toBe(true);
    expect(before(margin, narrative)).toBe(true);
    expect(before(scenarios, hypothesis)).toBe(true);
    // El margen sigue diciendo su cifra y su fórmula.
    expect(screen.getByText(/base del modelo de esta versión/)).toBeInTheDocument();
  });
});
