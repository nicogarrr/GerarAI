import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import type { OwnConsensusData, ReportInputs, ReportPeriod } from '@/lib/research/analyst-report';
import fixture from './analyst-report-asts.fixture.json';

const base = fixture as unknown as ReportInputs;
const view = (patch: Partial<ReportInputs> = {}, locale: 'es' | 'en' = 'es') =>
  render(<AnalystReportView data={{ ...base, ...patch }} t={createTranslator(locale)} fmt={createFormatters(locale)} locale={locale} />);

function withAnnual(rows: ReportPeriod[]): Partial<ReportInputs> {
  const report = { ...base.report!, estimates: { annual: rows, quarterly: [] } };
  return { report } as Partial<ReportInputs>;
}
const usd = (value: number) => ({ value, unit: 'USD', source: 'SEC', reported: true, basis: 'reported', derived_q4: false });

describe('EBITDA «—» con su motivo en la celda', () => {
  it('cada motivo del backend se lee en castellano bajo el guion', () => {
    view(withAnnual([
      { period_end: '2022-12-31', fiscal_quarter: 'FY', revenue: usd(1e9), ebitda: null, ebitda_reason: 'missing_da' },
      { period_end: '2023-12-31', fiscal_quarter: 'FY', revenue: usd(1e9), ebitda: null, ebitda_reason: 'missing_operating_income' },
      { period_end: '2024-12-31', fiscal_quarter: 'FY', revenue: usd(1e9), ebitda: null, ebitda_reason: 'financial_issuer' },
      { period_end: '2025-12-31', fiscal_quarter: 'FY', revenue: usd(1e9), ebitda: null, ebitda_reason: 'missing_operating_income_and_da' },
    ]));
    const table = screen.getByRole('table', { name: /Por ejercicio/ });
    const cells = within(table).getAllByTestId('informe-ebitda-reason').map((c) => c.textContent);
    expect(cells).toEqual([
      'sin amortizaciones (D&A)',
      'sin resultado operativo',
      'no aplica a bancos ni aseguradoras',
      'sin resultado operativo ni D&A',
    ]);
  });
  it('con cifra o sin motivo (backend antiguo) no añade texto', () => {
    view(withAnnual([
      { period_end: '2025-12-31', fiscal_quarter: 'FY', revenue: usd(1e9), ebitda: usd(2e8), ebitda_reason: null },
      { period_end: '2024-12-31', fiscal_quarter: 'FY', revenue: usd(1e9), ebitda: null },
    ]));
    expect(screen.queryAllByTestId('informe-ebitda-reason')).toHaveLength(0);
  });
  it('en inglés', () => {
    view(withAnnual([{ period_end: '2025-12-31', fiscal_quarter: 'FY', revenue: usd(1e9), ebitda: null, ebitda_reason: 'missing_da' }]), 'en');
    expect(screen.getByTestId('informe-ebitda-reason').textContent).toBe('no D&A');
  });
});

describe('consenso N/D: un motivo repetido se dice una vez', () => {
  const reason = 'ninguna fuente (guía de la empresa, analistas citados, modelo propio o tasa base) cumple los requisitos para este periodo';
  const nd = (metric: string, period: string, end: string) => ({ metric, period, period_end: end, status: 'sin_estimacion', source: null, mid: null, reason });
  const consensus = {
    version: 'consenso_propio v1',
    cells: [
      { metric: 'revenue', period: 'fy2027', period_end: '2027-09-30', status: 'estimado', source: 'modelo', mid: 400_000_000_000, citations: [] },
      nd('operating_income', 'fy2027', '2027-09-30'), nd('eps', 'fy2027', '2027-09-30'),
      { metric: 'revenue', period: 'fy2028', period_end: '2028-09-30', status: 'estimado', source: 'modelo', mid: 420_000_000_000, citations: [] },
      nd('operating_income', 'fy2028', '2028-09-30'), nd('eps', 'fy2028', '2028-09-30'),
    ],
  } as unknown as OwnConsensusData;
  it('el texto sale una sola vez (nota bajo el consenso), no en cada celda', () => {
    view({ consensus });
    const block = screen.getByTestId('informe-consensus');
    const text = block.textContent ?? '';
    expect(text.split(reason).length - 1).toBe(1);
    expect(within(block).getByTestId('consensus-common-reason').textContent).toContain(reason);
  });
  it('un motivo que solo sale en una celda sigue en su celda', () => {
    const single = { ...consensus, cells: [...consensus.cells.slice(0, 2).map((c) => c), { ...nd('eps', 'fy2027', '2027-09-30'), reason: 'otro motivo' }] } as unknown as OwnConsensusData;
    view({ consensus: single });
    expect(screen.queryByTestId('consensus-common-reason')).toBeNull();
  });
});
