import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TrackedAnalysisStatus } from '@/components/common/TrackedAnalysisStatus';
import { analysisStatusLabel } from '@/lib/tracked-analysis-status';

const as_of = '2026-10-19T08:30:00Z';
describe('estado del análisis de un ticker seguido en inglés', () => {
  it('labels in English', () => {
    expect(analysisStatusLabel({ status: 'running', as_of }, 'en')).toBe('Analyzing');
    expect(analysisStatusLabel({ status: 'dispatch_failed', as_of }, 'en')).toBe('Analysis waiting to retry');
    expect(analysisStatusLabel({ status: 'failed', as_of }, 'en')).toBe("The analysis couldn't be completed");
    expect(analysisStatusLabel({ status: 'succeeded', as_of }, 'en')).toBe('Analysis complete');
    expect(analysisStatusLabel({ status: 'weird', as_of }, 'en')).toBe('Analysis status not available');
    expect(analysisStatusLabel({ status: 'succeeded', as_of, thesis_status: 'insufficient_data', missing_inputs: ['annual_revenue_missing', 'shares_diluted'] }, 'en'))
      .toBe('Analysis: missing data (annual revenue and shares outstanding)');
    expect(analysisStatusLabel({ status: 'succeeded', as_of, thesis_status: 'insufficient_data', missing_inputs: ['fiscal_year', 'shares_diluted', 'normalized_fcf_margin', 'x'] }, 'en'))
      .toBe('Analysis: missing data (fiscal year end, shares outstanding and 2 more)');
  });
  it('Spanish unchanged, including the «y N más» tail', () => {
    expect(analysisStatusLabel({ status: 'succeeded', as_of, thesis_status: 'insufficient_data', missing_inputs: ['fiscal_year', 'shares_diluted', 'normalized_fcf_margin'] }))
      .toBe('Análisis: faltan datos (cierre de ejercicio y acciones en circulación y 1 más)');
  });
  it('component shows the English label and an English date', () => {
    render(<TrackedAnalysisStatus analysis={{ status: 'succeeded', as_of }} locale="en" />);
    expect(screen.getByText(/Analysis complete · .*Oct.*2026/)).toBeInTheDocument();
  });
});
