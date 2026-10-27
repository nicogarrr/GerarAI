import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { writeFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
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

describe('withheld valuation cannot escape through persisted thesis prose', () => {
  it.each(['published', 'draft', 'insufficient_data'])('withholds every free-text surface for %s when model is blocked', (status) => {
    render(<ThesisMemo thesis={{ ...fixture, status }} currency="USD" ticker="AAPL" model={{ publishable: false }} debateBody={archived} extraSections={[{ id: 99, title: 'Extra archive', body: archived }]} />);
    expect(screen.queryByText(/65,1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/119,92/)).not.toBeInTheDocument();
    expect(screen.queryByText('compra')).not.toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('Texto archivado de v11');
    expect(screen.getByRole('note')).toHaveTextContent('19 oct 2026');
    expect(screen.getByRole('note')).toHaveTextContent('no es publicable');
    expect(screen.queryByText(/rango indicativo parcial/)).not.toBeInTheDocument();
  });
  it.each([undefined, null, {}, { publishable: undefined }])('fails closed for absent or unknown model %j', (model) => {
    render(<ThesisMemo thesis={fixture} currency="USD" model={model as unknown as { publishable: boolean }} />);
    expect(screen.queryByText(/65,1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/119,92/)).not.toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('no se pudo verificar');
  });
  it('preserves source text and the historical formula warning when the valuation is not blocked', () => {
    render(<ThesisMemo thesis={fixture} currency="USD" model={{ publishable: true }} />);
    expect(screen.getByRole('note')).toHaveTextContent('fórmula no verificada');
    expect(screen.getAllByText(archived).length).toBeGreaterThan(0);
    expect(screen.getByText('compra')).toBeInTheDocument();
  });
});

it('exports the blocked component fixture for optional visual review', () => {
  if (process.env.WITHHELD_VISUAL_OUT) writeFileSync(process.env.WITHHELD_VISUAL_OUT, renderToStaticMarkup(<ThesisMemo thesis={fixture} currency="USD" />));
});
