import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ThesisSummary } from '@/components/research/ThesisSummary';
import { TtmPanel } from '@/components/research/TtmPanel';
import type { ResearchTtm } from '@/lib/research/ttm-display';
import { ttmPeriodText, ttmQuartersText } from '@/lib/research/ttm-display';

const thesis = { status: 'published', version: 11, created_at: '2026-10-19T06:54:00Z', executive_summary: 'Margin -65.1%' };
const ttm = (metrics: ResearchTtm['metrics']): ResearchTtm => ({ ticker: 'X', as_of: null, formula: 'TTM = sum of 4 quarters', metrics });

describe('ficha en inglés: resumen retenido de la tesis y panel TTM', () => {
  it('withheld thesis note reads in English with an English date', () => {
    render(<ThesisSummary thesis={thesis} model={{ publishable: false }} locale="en" />);
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Archived text from v11, generated on Oct 19, 2026: summary and figures withheld because the model is not publishable.');
    expect(note.textContent).not.toMatch(/archivado|retenidos|publicable/);
  });
  it('unpublished and unverified reasons in English', () => {
    render(<ThesisSummary thesis={{ ...thesis, status: 'draft', created_at: null }} model={{ publishable: true }} locale="en" />);
    expect(screen.getByRole('note')).toHaveTextContent('with no verified generation date: summary and figures withheld because the thesis is neither published nor approved');
  });
  it('Spanish stays the same', () => {
    render(<ThesisSummary thesis={thesis} model={null} />);
    expect(screen.getByRole('note')).toHaveTextContent('Texto archivado de v11, generada el 19 oct 2026: resumen y cifras retenidos porque no se pudo verificar que el modelo sea publicable.');
  });
  it('TTM panel empty state and cards in English', () => {
    render(<TtmPanel ttm={null} locale="en" />);
    expect(screen.getByText(/No saved quarters or fiscal years to calculate TTM/)).toBeInTheDocument();
    render(<TtmPanel locale="en" ttm={ttm([
      { metric: 'revenue', value: 12.5, unit: 'EUR', basis: 'TTM', label: 'x', provenance: 'INFERIDO', period_end: '2026-06-30',
        quarters: [{ period_end: '2025-12-31', value: 1, reported: false, origin: 'FY-9M' }, { period_end: '2026-03-31', value: 1, reported: true, origin: '10-Q' }] },
      { metric: 'net_income', value: null, unit: 'USD', basis: 'FY', label: 'x', provenance: 'SIN_DATOS', period_end: null },
      { metric: 'total_debt', value: 3, unit: 'USD', basis: 'FY', label: 'x', provenance: 'OFICIAL', period_end: '2025-12-31' },
    ])} />);
    expect(screen.getByText('INFERRED')).toBeInTheDocument();
    expect(screen.getByText('OFFICIAL')).toBeInTheDocument();
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.getByText('N/A')).toBeInTheDocument();
    expect(screen.getByText('TTM (last 4 quarters) · through 2026-06-30')).toBeInTheDocument();
    expect(screen.getByText('FY (latest fiscal year) · period ended 2025-12-31')).toBeInTheDocument();
    expect(screen.getByText('Sum of: 2025-12-31 (Q4 = FY − 9 months, inferred) + 2026-03-31')).toBeInTheDocument();
  });
  it('TTM helpers keep Spanish by default', () => {
    expect(ttmPeriodText({ basis: 'Q', period_end: '2026-06-30' })).toBe('Último trimestre · cierre 30/06/2026');
    expect(ttmQuartersText([{ period_end: '2026-03-31', value: 1, reported: false, origin: 'x' }], 'en')).toBe('2026-03-31 (year-to-date minus prior quarters, inferred)');
  });
});
