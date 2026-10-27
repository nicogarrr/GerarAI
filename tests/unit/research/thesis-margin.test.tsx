import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { writeFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
vi.mock('@/components/research/ThesisHumanInputForm', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisInvalidationRulesForm', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisDebatePanel', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisMarkdownPager', () => ({ default: () => null }));
vi.mock('@/components/GlossaryTerm', () => ({ GlossaryTerm: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
import ThesisMemo from '@/components/research/ThesisMemo';
import type { ResearchThesis } from '@/lib/actions/research.actions';

const fixture = {
  id: 1, company_id: 1, version: 11, status: 'published', rating: 'expensive',
  thesis_markdown: 'Original -64,9 %', executive_summary: 'Texto original archivado.',
  current_price: '343.46', bear_value: '42.82', base_value: '108.30', bull_value: '224.65', expected_value: '120.53',
  margin_of_safety: '-0.649', data_confidence_score: 80, source_coverage_score: 80,
  red_team_score: 80, valuation_risk_score: 80, created_at: '2026-10-19T06:54:00Z',
} as ResearchThesis;

describe('actual ThesisMemo historical margin', () => {
  it('warns with old backend raw value and keeps archive unchanged', () => {
    render(<ThesisMemo thesis={fixture} currency="USD" />);
    expect(screen.getByRole('note')).toHaveTextContent('fórmula no verificada');
    expect(screen.getByText('Margen archivado')).toBeInTheDocument();
    expect(screen.getByText('-64,9 %')).toBeInTheDocument();
    expect(screen.queryByText('sobre valor esperado')).not.toBeInTheDocument();
  });
  it('shows the archived API field if comparable is null', () => {
    render(<ThesisMemo thesis={{ ...fixture, margin_of_safety: null, archived_margin_of_safety: '-0.649' }} currency="USD" />);
    expect(screen.getByText('-64,9 %')).toBeInTheDocument();
    expect(screen.getByRole('note')).toBeInTheDocument();
  });
  it('shows verified formula and no warning for new explicit provenance', () => {
    render(<ThesisMemo thesis={{ ...fixture, margin_of_safety: '-1.849581', valuation_basis: { margin_of_safety_convention: 'discount_to_value_v1' } }} currency="USD" />);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    expect(screen.getByText(/base del modelo de esta versión/)).toBeInTheDocument();
  });
  it('does not leak a draft archived percentage', () => {
    render(<ThesisMemo thesis={{ ...fixture, status: 'draft' }} currency="USD" />);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    expect(screen.queryByText('-64,9 %')).not.toBeInTheDocument();
  });
  it('captures full real memo SSR for pixel review with interactive children stubbed', () => {
    if (process.env.MOS_VISUAL_OUT) {
      const visualFixture = process.env.MOS_VERIFIED ? { ...fixture, margin_of_safety: '-1.849581', valuation_basis: { margin_of_safety_convention: 'discount_to_value_v1' } } : fixture;
      writeFileSync(process.env.MOS_VISUAL_OUT, renderToStaticMarkup(<ThesisMemo thesis={visualFixture} currency="USD" />));
    }
    cleanup();
  });
});
