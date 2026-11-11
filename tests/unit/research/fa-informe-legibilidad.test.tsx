import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import { readableMissingReason } from '@/lib/research/missing-reason';
import type { ReportInputs } from '@/lib/research/analyst-report';
import fixture from './analyst-report-asts.fixture.json';

// Auditoría del Informe en iPhone/PC (r5, 11-nov-2026): lo que se lee mal.
const base = fixture as unknown as ReportInputs;
function view(patch: Partial<ReportInputs> = {}, locale: 'es' | 'en' = 'es') {
  return render(<AnalystReportView data={{ ...base, ...patch }} t={createTranslator(locale)} fmt={createFormatters(locale)} locale={locale} />);
}
const legacyCard = () => {
  const card = structuredClone(base.card)!;
  card.current = { ...card.current!, label: '1X DCA', zone: 'Zona de aportacion normal' };
  return card;
};

describe('motivos N/D legibles', () => {
  it('las claves internas del motor se leen en castellano y el verbo concuerda', () => {
    expect(readableMissingReason('La última valoración del motor del 8 nov 2026 no dio cifra: faltan fx_rate:TWD/USD.')).toBe('La última valoración del motor del 8 nov 2026 no dio cifra: falta tipo de cambio TWD/USD.');
    expect(readableMissingReason('La última valoración del motor no dio cifra: faltan net_debt, fcf.')).toMatch(/faltan deuda neta y /);
    expect(readableMissingReason('The latest engine valuation produced no value: missing net_debt.', 'en')).not.toContain('net_debt');
  });
  it('un motivo ya redactado pasa tal cual', () => {
    const free = 'La última valoración del motor no dio cifra: el sector no tiene múltiplos comparables.';
    expect(readableMissingReason(free)).toBe(free);
    expect(readableMissingReason('Faltan datos: periodos no comparables.')).toBe('Faltan datos: periodos no comparables.');
  });
});

describe('cabecera del Informe', () => {
  it('el nivel DCA usa la etiqueta corregida (con tilde) y en inglés se traduce', () => {
    view({ card: legacyCard() });
    const head = screen.getByTestId('informe-dca').parentElement!;
    expect(head.textContent).toContain('Zona de aportación normal · ');
    expect(screen.getByTestId('analyst-report').textContent).not.toContain('aportacion normal');
  });
  it('en inglés la zona DCA de la cabecera no sale en castellano', () => {
    view({ card: legacyCard() }, 'en');
    expect(screen.getByTestId('informe-dca').parentElement!.textContent).toContain('Normal contribution zone · ');
  });
  it('sin valor justo: un titular y su motivo legible, sin la etiqueta repetida ni claves crudas', () => {
    view({ fair: { value: null, currency: null, label: 'Sin valor justo', as_of: null, publishable: false, reason: 'La última valoración del motor del 8 nov 2026 no dio cifra: faltan fx_rate:TWD/USD.' } });
    expect(screen.getByTestId('informe-fair').textContent).toBe('Sin valor justo fiable');
    expect(screen.getByTestId('informe-fair-reason').textContent).toContain('tipo de cambio TWD/USD');
    const header = screen.getByTestId('informe-fair').parentElement!;
    expect(header.textContent).not.toContain('fx_rate');
    expect(within(header).queryByText('Sin valor justo')).toBeNull();
  });
  it('rango N/D con su motivo', () => {
    view({ fair: null, thesis: null, engineRange: null });
    expect(screen.getByTestId('informe-range').textContent).toBe('N/D');
    expect(screen.getByText('Sin escenarios en la tesis publicada ni rango del motor')).toBeTruthy();
  });
});

describe('consenso propio en táctil y en PC', () => {
  const consensus = { cells: [
    { metric: 'revenue', period: 'fy2027', period_end: '2027-12-31', status: 'estimado', mid: 4.21e12, source: 'tasa_base', formula: 'ingresos FY2025 × (1 + mediana de comparables)²' },
    { metric: 'operating_income', period: 'fy2027', period_end: '2027-12-31', status: 'sin_datos', reason: 'Ninguna fuente con fecha de publicación.' },
    { metric: 'eps', period: 'fy2027', period_end: '2027-12-31', status: 'estimado', mid: 72.33, source: 'modelo', formula: 'BPA FY2025 × EBIT estimado / EBIT FY2025' },
  ] } as unknown as ReportInputs['consensus'];
  const twd = () => {
    const report = structuredClone(base.report)!;
    report.estimates.annual = report.estimates.annual.map((r) => ({ ...r, revenue: r.revenue ? { ...r.revenue, unit: 'TWD' } : r.revenue }));
    return report;
  };
  it('la fórmula se abre con un toque en el móvil (sin depender del ratón)', () => {
    view({ consensus, report: twd() });
    const card = screen.getByRole('region', { name: /Consenso.*27/ });
    const formulas = within(card).getAllByTestId('consensus-formula');
    expect(formulas).toHaveLength(2);
    expect(formulas[0].tagName).toBe('DETAILS');
    expect(formulas[0].textContent).toContain('mediana de comparables');
    expect(screen.getByTestId('informe-consensus').textContent).not.toMatch(/Pasa el ratón/);
  });
  it('en la tabla de PC el motivo del N/D se ve, no solo en el title', () => {
    view({ consensus, report: twd() });
    const table = within(screen.getByTestId('informe-consensus')).getByRole('table');
    expect(within(table).getByText('Ninguna fuente con fecha de publicación.')).toBeTruthy();
  });
  it('el BPA lleva la divisa del ejercicio', () => {
    view({ consensus, report: twd() });
    const table = within(screen.getByTestId('informe-consensus')).getByRole('table');
    const row = within(table).getAllByRole('row')[1];
    expect(row.textContent).toMatch(/72,33\s?(NT\$|TWD)/);
  });
});
