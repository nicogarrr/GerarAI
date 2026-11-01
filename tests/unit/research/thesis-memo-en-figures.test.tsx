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
import { periodEn, provenanceBasis } from '@/lib/research/provenance-groups';
import { thesisEps, thesisMoney } from '@/lib/research/thesis-number-format';
import { thesisScenarioDisplay } from '@/lib/research/listed-share-values';

const fixture = {
  id: 1, company_id: 1, version: 3, status: 'published', rating: 'buy',
  thesis_markdown: '', executive_summary: '', hypothesis: '', narrative_sections: [],
  catalysts: [{ label: 'Q3', eps_forecast: 1234.5 }], invalidation_criteria: [],
  current_price: '1343.46', bear_value: '1042.82', base_value: '1108.30', bull_value: '1224.65', expected_value: '1119.92',
  margin_of_safety: '-0.651', data_confidence_score: 80, source_coverage_score: 80,
  red_team_score: 80, valuation_risk_score: 80, created_at: '2026-10-19T06:54:00Z',
  inputs_provenance: [
    { key: 'fcf_margin', value: 0.25, unit: 'ratio', label: 'supuesto', base_inferencia: 'mediana de las últimas 5 observaciones anuales de fcf_margin' },
  ],
} as unknown as ResearchThesis;

describe('memorando de tesis en inglés: cifras y bases', () => {
  it('importes, BPA, margen, métricas y base en inglés', () => {
    render(<ThesisMemo thesis={fixture} currency="USD" ticker="AAPL" model={{ publishable: true }} locale="en" />);
    expect(screen.getAllByText('$1,108.30').length).toBeGreaterThan(0);
    expect(screen.queryByText(/1\.108,30/)).not.toBeInTheDocument();
    expect(screen.getByText(/EPS est\..*1,234\.50/)).toBeInTheDocument();
    expect(screen.getByText('Median of the latest 5 annual observations of FCF margin')).toBeInTheDocument();
    expect(screen.getAllByText(/per-share basis not verified/)[0]).toBeInTheDocument();
    expect(screen.queryByText(/Mediana de las|base por acción|Margen FCF/)).not.toBeInTheDocument();
  });
  it('en español no cambia', () => {
    render(<ThesisMemo thesis={fixture} currency="USD" ticker="AAPL" model={{ publishable: true }} />);
    expect(screen.getAllByText(/^1\.108,30\sUS\$$/).length).toBeGreaterThan(0);
    expect(screen.getByText('Mediana de las últimas 5 observaciones anuales de margen fcf')).toBeInTheDocument();
    expect(screen.getAllByText(/base por acción no verificada/)[0]).toBeInTheDocument();
  });
  it('helpers con locale', () => {
    expect(thesisMoney(1522.6, 'EUR', 'en')).toBe('€1,522.60');
    expect(thesisMoney(1522.6, 'EUR')).toMatch(/^1\.522,60\s€$/);
    expect(thesisEps(null, 'en')).toBe('N/A');
    expect(thesisEps(null)).toBe('N/D');
    expect(periodEn('2025-09-27:FY')).toBe('fiscal year 2025 (ended Sep 27, 2025)');
    expect(periodEn('2026-06-30:Q2')).toBe('Q2 2026 (ended Jun 30, 2026)');
    expect(provenanceBasis('revenue reportado (periodo 2025-09-27:FY)', 'en')).toBe('Reported, fiscal year 2025 (ended Sep 27, 2025)');
    expect(provenanceBasis('sin observaciones anuales de market_cap', 'en')).toBe('No annual observations of market capitalization');
    expect(provenanceBasis('dado revenue reportado', 'es')).toBe('Reportado');
    expect(thesisScenarioDisplay({ bear: 1, base: 2, bull: 3, expected: 2 }, { adr_ratio: 8, listed_share_values: null } as never, 'en').label).toBe(' (per-share basis not verified)');
  });
});
