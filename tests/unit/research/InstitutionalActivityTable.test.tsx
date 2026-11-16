import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { InstitutionalActivityTable } from '@/components/research/InstitutionalActivityTable';
import type { InstitutionalActivity, InstitutionalActivityRow } from '@/lib/research/institutional-holders';

const row: InstitutionalActivityRow = { cik: '0000000001', name: 'Manager One', status: 'aumenta', shares: 150, prev_shares: 100, change: 50, change_pct: 50, reported_value_usd: 12345, company_ownership_pct: null, filed: '2026-08-15', filing_url: 'https://www.sec.gov/filing', prev_filing_url: null };
const data: InstitutionalActivity = { ticker: 'ASTS', cusip: '00217D100', identity_source: 'synthetic', status: 'ok', period: '2026-06-30', prior_period: '2026-03-31', fetched_at: '2026-11-16', filter: 'all', page: 1, page_size: 25, total: 63, pages: 3, rows: [row] };
const baseHref = '/research/ASTS?view=seguimiento&years=5';

describe('InstitutionalActivityTable', () => {
  it('renders accessible columns, reported values and honest capital N/D with query pagination', () => {
    render(<InstitutionalActivityTable data={data} locale="es" baseHref={baseHref} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '% del capital' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Manager One' })).toHaveAttribute('href', row.filing_url);
    expect(screen.getByRole('cell', { name: 'N/D' })).toBeInTheDocument();
    expect(screen.getByText(/no flujo de compra o venta/)).toBeInTheDocument();
    const next = screen.getByRole('link', { name: 'Siguiente' });
    expect(next).toHaveAttribute('href', '/research/ASTS?view=seguimiento&years=5&ia_status=all&ia_page=2#superinversores');
    expect(screen.getByRole('link', { name: 'Nuevos' })).toHaveAttribute('href', '/research/ASTS?view=seguimiento&years=5&ia_status=nuevo&ia_page=1#superinversores');
    expect(screen.queryByRole('link', { name: 'Anterior' })).not.toBeInTheDocument();
  });

  it.each([
    ['sin_detalle', /solo conserva un resumen/], ['sin_snapshot_vinculado', /identificador actual/],
    ['sin_datos', /No significa cero movimientos/], ['sin_identificador', /Sin identificador verificado/],
  ] as const)('keeps %s distinct, never claims zero activity', (status, message) => {
    render(<InstitutionalActivityTable data={{ ...data, status }} locale="es" baseHref={baseHref} />);
    expect(screen.getByRole('status')).toHaveTextContent(message);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows request error instead of missing data', () => {
    render(<InstitutionalActivityTable data={null} locale="en" baseHref={baseHref} />);
    expect(screen.getByRole('status')).toHaveTextContent('Institutional activity could not be loaded.');
  });

  it('shows all missing sides as N/A, retains zero, links prior filings and English statuses', () => {
    const rows: InstitutionalActivityRow[] = ['sin_13f_aun', 'sin_13f_previo', 'igual', '', 'nuevo', 'reduce', 'vende_todo'].map((status, i) => ({ ...row, cik: String(i), name: i ? `Manager ${i}` : '', status: status as InstitutionalActivityRow['status'], shares: i ? 0 : null, prev_shares: null, change: null, reported_value_usd: null, company_ownership_pct: i === 2 ? 1 : null, filing_url: null, prev_filing_url: i === 0 ? 'https://www.sec.gov/prior' : null }));
    render(<InstitutionalActivityTable data={{ ...data, filter: 'nuevo', page: 3, rows }} locale="en" baseHref="/research/ASTS" />);
    expect(screen.getByRole('link', { name: '0' })).toHaveAttribute('href', 'https://www.sec.gov/prior');
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(10);
    expect(within(screen.getByRole('table')).getAllByText('0').length).toBeGreaterThan(1);
    expect(screen.getByRole('link', { name: 'Previous' })).toHaveAttribute('href', '/research/ASTS?ia_status=nuevo&ia_page=2#superinversores');
    expect(screen.queryByRole('link', { name: 'Next' })).not.toBeInTheDocument();
  });

  it('shows empty filter, unavailable periods and valid zero total', () => {
    render(<InstitutionalActivityTable data={{ ...data, rows: [], pages: null, total: null, period: null, prior_period: null }} baseHref="/research/ASTS?view=seguimiento#superinversores" />);
    expect(screen.getByRole('status')).toHaveTextContent('No hay filas para este filtro');
    expect(screen.getByText('Página 1 de 1 · 0 gestores')).toBeInTheDocument();
  });
  it.each([['es', '1,0'], ['en', '1.0']] as const)('uses the shared locale percentage formatter for %s', (locale, number) => {
    render(<InstitutionalActivityTable data={{ ...data, rows: [{ ...row, company_ownership_pct: 1 }] }} locale={locale} baseHref={baseHref} />);
    const values = screen.getAllByRole('cell').map(cell => cell.textContent);
    expect(values).toContain(locale === 'en' ? `${number}%` : `${number}\u00a0%`);
  });

});
