import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { InstitutionalHoldersPanel } from '@/components/research/InstitutionalHoldersPanel';
import type { InstitutionalHolders } from '@/lib/research/institutional-holders';

const holder = (over: Partial<InstitutionalHolders['top_holders'][number]>) => ({
  cik: '0000000001', name: 'Alpha', shares: 150, prev_shares: 100, change: 50, change_pct: 50, pct_of_13f: 56.6, status: 'aumenta' as const,
  accession: 'Q2-A', filed: '2026-08-10', filing_url: 'https://www.sec.gov/Archives/edgar/data/1/Q2A/Q2-A-index.htm', prev_filing_url: null, ...over,
});

const data: InstitutionalHolders = {
  status: 'ok', ticker: 'AAPL', name: 'Apple', cusip: '037833100', identity_source: 'CUSIP derivado del ISIN registrado',
  period: '2026-06-30', prior_period: '2026-03-31',
  source: { dataset_url: 'https://www.sec.gov/files/x/01jun2026-31aug2026_form13f.zip', prior_dataset_url: null, fetched_at: '2026-11-08T00:00:00Z', page: 'https://www.sec.gov/x' },
  totals: { holders: 4, holders_prior: 5, shares: 265, shares_prior: 205, net_comparable: 10, nuevo: 1, aumenta: 1, reduce: 1, igual: 1, vende_todo: 1, sin_13f_aun: 1, sin_13f_previo: 0 },
  top_holders: [holder({})],
  buyers: [holder({ name: 'Phi', cik: '6', shares: 70, prev_shares: 0, change: 70, change_pct: null, status: 'nuevo' })],
  sellers: [holder({ name: 'Gamma', cik: '3', shares: 0, prev_shares: 30, change: -30, change_pct: -100, status: 'vende_todo', filing_url: null, prev_filing_url: 'https://www.sec.gov/Archives/edgar/data/3/Q1C/Q1-C-index.htm' })],
  limitations: ['13F: trimestral.'],
};

// Nico, 8-nov-2026: «quién compra y quién vende» de AITerminal, dentro de la
// sección Superinversores de la ficha (sin pestaña nueva).
describe('InstitutionalHoldersPanel', () => {
  it('muestra mayores tenedores, compradores y vendedores con su 13F enlazado', () => {
    render(<InstitutionalHoldersPanel data={data} locale="es" />);
    expect(screen.getByText('Todos los gestores 13F')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Alpha' })).toHaveAttribute('href', data.top_holders[0].filing_url);
    expect(screen.getByText('Quién compra')).toBeInTheDocument();
    expect(screen.getByText('Nueva')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Gamma' })).toHaveAttribute('href', 'https://www.sec.gov/Archives/edgar/data/3/Q1C/Q1-C-index.htm');
    expect(screen.getByText('Vende todo')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Fichero de la SEC' })).toHaveAttribute('href', data.source?.dataset_url);
    expect(screen.getByText(/4 gestores declaran/)).toBeInTheDocument();
  });

  it('sin datos o sin CUSIP lo dice, sin inventar cifras', () => {
    const { rerender } = render(<InstitutionalHoldersPanel data={{ ...data, status: 'sin_datos', totals: undefined }} locale="es" />);
    expect(screen.getByRole('status')).toHaveTextContent('Aún no se ha cargado');
    rerender(<InstitutionalHoldersPanel data={{ ...data, status: 'sin_identificador', identity_source: null, totals: undefined }} locale="es" />);
    expect(screen.getByRole('status')).toHaveTextContent('Sin CUSIP verificado');
    rerender(<InstitutionalHoldersPanel data={null} locale="es" />);
    expect(screen.getByRole('status')).toHaveTextContent('No se pudieron cargar');
  });

  it('las columnas pueden encoger: un nombre largo se recorta en vez de ensanchar la ficha en el móvil', () => {
    const { container } = render(<InstitutionalHoldersPanel data={data} locale="es" />);
    const columns = container.querySelectorAll('[data-testid="institucionales"] .grid > div');
    expect(columns.length).toBeGreaterThan(1);
    columns.forEach((column) => expect(column).toHaveClass('min-w-0'));
  });
});
