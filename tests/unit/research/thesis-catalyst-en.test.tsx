import React from 'react';
import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/components/research/ThesisHumanInputForm', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisInvalidationRulesForm', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisDebatePanel', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisMarkdownPager', () => ({ default: () => null }));
vi.mock('@/components/GlossaryTerm', () => ({ GlossaryTerm: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
import ThesisMemo from '@/components/research/ThesisMemo';
import type { ResearchThesis } from '@/lib/actions/research.actions';
import { thesisCatalystLabel } from '@/lib/research/catalyst-label';
import { createTranslator } from '@/lib/i18n/translate';

// Etiqueta real del catalizador de resultados (thesis_service._catalysts, leída del .py).
const PY = readFileSync('data-engine/app/services/thesis_service.py', 'utf8');
const LABEL = /"label": "([^"]+)",\s*"date": earnings\.get\("next_date"\)/.exec(PY)?.[1] ?? '';

const thesis = {
  id: 1, company_id: 1, version: 3, status: 'published', rating: 'hold',
  thesis_markdown: '', executive_summary: '', hypothesis: '',
  catalysts: [{ label: LABEL, date: '2026-11-05', source: 'earnings_calendar' }], invalidation_criteria: [],
  current_price: '100', bear_value: '80', base_value: '110', bull_value: '140', expected_value: '112',
  margin_of_safety: '0.1', data_confidence_score: 80, source_coverage_score: 80, red_team_score: 80, valuation_risk_score: 80,
  created_at: '2026-10-19T06:54:00Z',
} as unknown as ResearchThesis;

describe('catalizador de resultados de la tesis en inglés', () => {
  it('la etiqueta de prueba es la del backend', () => {
    expect(LABEL).toBe('Próximos resultados');
  });
  it('el memorando en inglés dice «Upcoming earnings»', () => {
    const { container } = render(<ThesisMemo thesis={thesis} currency="USD" ticker="AAPL" model={{ publishable: true }} locale="en" />);
    expect(screen.getByText('Upcoming earnings')).toBeInTheDocument();
    expect(container.textContent).not.toContain(LABEL);
  });
  it('en castellano sigue la etiqueta del backend', () => {
    render(<ThesisMemo thesis={thesis} currency="USD" ticker="AAPL" model={{ publishable: true }} />);
    expect(screen.getByText(LABEL)).toBeInTheDocument();
  });
  it('la página de lectura usa el mismo helper; otra etiqueta pasa tal cual', () => {
    const en = createTranslator('en');
    expect(thesisCatalystLabel(LABEL, 'en', en)).toBe('Upcoming earnings');
    expect(thesisCatalystLabel(LABEL, 'es', createTranslator('es'))).toBe(LABEL);
    expect(thesisCatalystLabel('Junta de accionistas', 'en', en)).toBe('Junta de accionistas');
  });
});
