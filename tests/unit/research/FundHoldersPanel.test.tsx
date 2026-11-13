import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FundHoldersPanel } from '@/components/research/FundHoldersPanel';
import { datasetLabel, fundHoldersExtraNotices } from '@/lib/research/fund-holders';
import type { FundHolders } from '@/lib/research/fund-holders';

const fund = (over: Partial<FundHolders['top_funds'][number]>) => ({
  series_id: 'S000000001', name: 'Big Index Fund', accession: 'A1', report_date: '2026-06-30', filed: '2026-08-20', shares: 1000,
  value_usd: 200000, weight_pct: 3.5, net_assets_usd: 500000, filing_url: 'https://www.sec.gov/Archives/edgar/data/100/A1/A1-index.htm', ...over,
});

const data: FundHolders = {
  status: 'ok', ticker: 'AAPL', name: 'Apple', cusip: '037833100', identity_source: null, dataset: '2026q3',
  source: { dataset_url: 'https://www.sec.gov/files/dera/data/form-n-port-data-sets/2026q3_nport.zip', page: 'https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets', fetched_at: '2026-11-08T00:00:00Z' },
  totals: { funds: 2, shares: 1060, value_usd: 212000 },
  top_funds: [fund({})],
  by_weight: [fund({ series_id: 'S000000002', name: 'Theme ETF', accession: 'B2', shares: 60, weight_pct: 9, value_usd: 12000, filing_url: null })],
  limitations: [],
};

// Nico, 8-nov-2026 (AITerminal): «qué ETF la tienen», dentro de la sección de
// propietarios de la ficha, sin pestaña nueva.
describe('FundHoldersPanel', () => {
  it('muestra los fondos con más acciones y donde más pesa, con su N-PORT y su fecha', () => {
    render(<FundHoldersPanel data={data} locale="es" />);
    expect(screen.getByText('Fondos y ETF que la tienen')).toBeInTheDocument();
    expect(screen.getByText(/2 fondos y ETF de EE\. UU\./)).toBeInTheDocument();
    expect(screen.getByText(/3T 2026/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Big Index Fund' })).toHaveAttribute('href', data.top_funds[0].filing_url);
    expect(screen.getByText('Donde más pesa')).toBeInTheDocument();
    expect(screen.getByText('Theme ETF')).toBeInTheDocument();
    expect(screen.getByText(/9,0 %/)).toBeInTheDocument();
    expect(screen.getAllByText(/cartera a 30 jun 2026/).length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: 'SEC Form N-PORT Data Sets' })).toHaveAttribute('href', data.source?.page);
  });

  it('estados honestos: sin CUSIP, sin datos y error de carga', () => {
    const { rerender } = render(<FundHoldersPanel data={{ ...data, status: 'sin_identificador', identity_source: null, totals: undefined }} locale="es" />);
    expect(screen.getByRole('status')).toHaveTextContent(/Sin CUSIP verificado/);
    rerender(<FundHoldersPanel data={{ ...data, status: 'sin_datos', totals: undefined }} locale="es" />);
    expect(screen.getByRole('status')).toHaveTextContent(/Aún no hay carteras N-PORT/);
    rerender(<FundHoldersPanel data={null} locale="es" />);
    expect(screen.getByRole('status')).toHaveTextContent(/No se pudieron cargar/);
  });

  it('las columnas pueden encoger: un nombre largo se recorta en vez de ensanchar la ficha en el móvil', () => {
    const { container } = render(<FundHoldersPanel data={data} locale="es" />);
    const columns = container.querySelectorAll('[data-testid="fondos"] .grid > div');
    expect(columns.length).toBeGreaterThan(1);
    columns.forEach((column) => expect(column).toHaveClass('min-w-0'));
  });

  it('avisos N-PORT del backend: traducidos en inglés, sin repetir las limitaciones del pie', () => {
    const noticed: FundHolders = {
      ...data,
      totals: { funds: 2, shares: 1060, value_usd: null },
      limitations: [
        'N-PORT: fondos y ETF registrados en EE. UU.; la cartera pública es la del último mes de cada trimestre fiscal del fondo, con hasta 60 días de retraso.',
        'Cada fondo tiene su propia fecha de cartera (se muestra); no son todas del mismo día.',
        'Peso = % del patrimonio neto que declara el propio fondo.',
        'Snapshot N-PORT previo: integridad de importes y pesos no verificada hasta recalcular.',
        'Datos N-PORT incompletos: los importes o pesos con componentes ausentes no se presentan como totales completos.',
        'Aviso nuevo del backend',
      ],
    };
    const { rerender } = render(<FundHoldersPanel data={noticed} locale="es" />);
    expect(screen.getByText(/Snapshot N-PORT previo/)).toBeInTheDocument();
    expect(screen.getByText(/Datos N-PORT incompletos/)).toBeInTheDocument();
    expect(screen.getByText('Aviso nuevo del backend')).toBeInTheDocument();
    expect(screen.queryByText(/Cada fondo tiene su propia fecha de cartera/)).not.toBeInTheDocument();
    rerender(<FundHoldersPanel data={noticed} locale="en" />);
    expect(screen.getByText('Previous N-PORT snapshot: amount and weight integrity not verified until recomputed.')).toBeInTheDocument();
    expect(screen.getByText('Incomplete N-PORT data: amounts or weights with missing components are not shown as complete totals.')).toBeInTheDocument();
    expect(screen.getByText('Aviso nuevo del backend')).toBeInTheDocument();
    expect(screen.queryByText(/Datos N-PORT incompletos/)).not.toBeInTheDocument();
  });

  it('datasetLabel traduce el trimestre del fichero y respeta valores raros', () => {
    expect(datasetLabel('2026q3', 'es')).toBe('3T 2026');
    expect(datasetLabel('2026q3', 'en-US')).toBe('Q3 2026');
    expect(datasetLabel('trimestre-raro', 'es')).toBe('trimestre-raro');
    expect(datasetLabel(undefined, 'es')).toBe('—');
    expect(fundHoldersExtraNotices(undefined)).toEqual([]);
  });

  it('cero observado: la acción no aparece en el fichero, no «0 fondos declaran 0 acciones»', () => {
    const zero: FundHolders = { ...data, totals: { funds: 0, shares: 0, value_usd: 0 }, top_funds: [], by_weight: [] };
    render(<FundHoldersPanel data={zero} locale="es" />);
    expect(screen.getByRole('status')).toHaveTextContent(/no aparece en el fichero N-PORT 3T 2026/);
    expect(screen.queryByText(/0 fondos y ETF/)).not.toBeInTheDocument();
  });

  it('cero observado en inglés', () => {
    const zero: FundHolders = { ...data, totals: { funds: 0, shares: 0, value_usd: 0 }, top_funds: [], by_weight: [] };
    render(<FundHoldersPanel data={zero} locale="en" />);
    expect(screen.getByRole('status')).toHaveTextContent(/does not appear in the Q3 2026 N-PORT file/);
  });
});


describe('FundHoldersPanel: acciones ausentes no son cero', () => {
  it.each(['es', 'en'] as const)('acciones null: N/D localizado en ambas listas (%s)', (locale) => {
    const missing: FundHolders = { ...data,
      top_funds: [fund({ shares: null })],
      by_weight: [fund({ accession: 'B2', name: 'Theme ETF', shares: null })],
    };
    render(<FundHoldersPanel data={missing} locale={locale} />);
    const na = locale === 'es' ? 'N/D' : 'N/A';
    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]).getByText(na)).toBeInTheDocument();
    expect(rows[1]).toHaveTextContent(locale === 'es' ? `${na} acciones` : `${na} shares`);
    expect(rows[1]).not.toHaveTextContent(locale === 'es' ? /\b0 acciones/ : /\b0 shares/);
  });

  it.each([NaN, Infinity, -Infinity])('acciones no finitas: N/D, no %s', (shares) => {
    render(<FundHoldersPanel data={{ ...data, top_funds: [fund({ shares })] }} locale="es" />);
    expect(within(screen.getAllByRole('listitem')[0]).getByText('N/D')).toBeInTheDocument();
  });

  it('cero reportado conserva 0, no lo confunde con ausencia', () => {
    render(<FundHoldersPanel data={{ ...data, top_funds: [fund({ shares: 0 })] }} locale="es" />);
    expect(within(screen.getAllByRole('listitem')[0]).getByText('0')).toBeInTheDocument();
  });
});


it('fondos sin enlace al dataset conservan la atribución de la SEC', () => {
  render(<FundHoldersPanel data={{ ...data, source: undefined }} locale="es" />);
  expect(screen.queryByRole('link', { name: 'SEC Form N-PORT Data Sets' })).not.toBeInTheDocument();
  expect(screen.getByTestId('fondos')).toHaveTextContent('SEC Form N-PORT Data Sets');
});
