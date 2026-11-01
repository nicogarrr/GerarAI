import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/components/research/ThesisHumanInputForm', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisInvalidationRulesForm', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisDebatePanel', () => ({ default: ({ initialVerdict }: { initialVerdict?: string }) => <div>{initialVerdict}</div> }));
vi.mock('@/components/research/ThesisMarkdownPager', () => ({ default: ({ pages }: { pages: { body: string }[] }) => <div>{pages.map((p, i) => <p key={i}>{p.body}</p>)}</div> }));
vi.mock('@/components/GlossaryTerm', () => ({ GlossaryTerm: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
import ThesisMemo from '@/components/research/ThesisMemo';
import type { ResearchThesis } from '@/lib/actions/research.actions';

const archived = 'Margen de seguridad -65,1% respecto al valor esperado 119,92';
const fixture = {
  id: 1, company_id: 1, version: 11, status: 'published', rating: 'buy',
  thesis_markdown: `## Valoración\n${archived}`, executive_summary: archived, hypothesis: archived,
  narrative_sections: [{ titulo: 'Narrativa archivada', parrafos: [archived] }],
  catalysts: [{ label: archived }], invalidation_criteria: [archived],
  current_price: '343.46', bear_value: '42.82', base_value: '108.30', bull_value: '224.65', expected_value: '119.92',
  margin_of_safety: '-0.651', archived_margin_of_safety: '-0.651', data_confidence_score: 80, source_coverage_score: 80,
  red_team_score: 80, valuation_risk_score: 80, created_at: '2026-10-19T06:54:00Z',
} as ResearchThesis;

describe('memorando de tesis en inglés', () => {
  it('etiquetas, estado y secciones en inglés con el modelo publicable', () => {
    render(<ThesisMemo thesis={{ ...fixture, valuation_basis: { margin_of_safety_convention: 'discount_to_value_v1' } } as ResearchThesis} currency="USD" ticker="AAPL" model={{ publishable: true }} locale="en" />);
    expect(screen.getByText('buy')).toBeInTheDocument();
    expect(screen.queryByText('compra')).not.toBeInTheDocument();
    expect(screen.getByText('Scenarios and valuation')).toBeInTheDocument();
    expect(screen.getByText('Evidence quality')).toBeInTheDocument();
    expect(screen.getByText('What would invalidate the thesis')).toBeInTheDocument();
    expect(screen.getByText(/generated on Oct 19, 2026/)).toBeInTheDocument();
    expect(screen.queryByText(/Escenarios|Calidad de la evidencia|generada el/)).not.toBeInTheDocument();
  });
  it('retenida: el aviso sale en inglés', () => {
    render(<ThesisMemo thesis={fixture} currency="USD" model={{ publishable: false }} locale="en" />);
    expect(screen.getByRole('note')).toHaveTextContent('Archived text from v11, generated on');
    expect(screen.getByRole('note')).toHaveTextContent("the model isn't publishable");
    expect(screen.getByText('insufficient data')).toBeInTheDocument();
  });
  it('en español no cambia', () => {
    render(<ThesisMemo thesis={fixture} currency="USD" model={{ publishable: false }} />);
    expect(screen.getByRole('note')).toHaveTextContent('Texto archivado de v11');
    expect(screen.getByText('datos insuficientes')).toBeInTheDocument();
  });
});
