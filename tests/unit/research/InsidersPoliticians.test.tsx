import { render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';

import { InsidersSection } from '@/components/research/InsidersSection';
import { PoliticiansSection } from '@/components/research/PoliticiansSection';
import { PoliticianCardView } from '@/components/research/PoliticianCard';
import { amountRange } from '@/lib/research/insiders-politicians';
import type { InsiderSummary, PoliticianTickerTrades } from '@/lib/research/insiders-politicians';

const side = (trades: number, value: number, planned = 0) => ({ trades, insiders: trades ? 1 : 0, shares: 0, value, value_missing: 0, planned_10b5_1: planned });

// Forma real de /api/insider/summary (POOL, 8-nov-2026, datos locales).
const summary: InsiderSummary = {
  ticker: 'POOL',
  as_of: '2026-11-08',
  status: 'ok',
  source: 'SEC EDGAR · Form 4/5',
  coverage: { first_filing: '2025-12-01', last_filing: '2026-08-14', filings: 49, transactions: 68, with_holdings_after: 68 },
  windows: [
    { days: 90, buys: side(0, 0), sells: side(0, 0), net_value: 0, excluded: { regalo: 2 }, covered: true },
    { days: 180, buys: side(1, 1759471), sells: side(0, 0), net_value: 1759471, excluded: { regalo: 2 }, covered: true },
    { days: 365, buys: side(10, 7673698), sells: side(5, 1936271, 2), net_value: 5737427, excluded: { concesion: 21, retencion_fiscal: 11, regalo: 9 }, covered: false },
  ],
  clusters: [{ start: '2026-05-07', end: '2026-05-13', insiders: 4, names: ['Hope James D', 'PEREZ DE LA MESA MANUEL J'], trades: 5, value: 4042725.56 }],
  first_buys: [],
  late: { filings: 49, late: 0 },
  transactions: [{
    insider: 'PEREZ DE LA MESA MANUEL J', role: 'director', form: '4', code: 'P', nature: 'compra_mercado', is_derivative: false,
    rule_10b5_1: false, shares: 10000, price: 190, value: 1900000, holdings_after: 30108, ownership: 'D', pct_of_holdings: 49.73,
    tx_date: '2026-05-07', filing_date: '2026-05-08', days_late: 0, late: false, accession_number: '0001-26-1',
    source_url: 'https://www.sec.gov/Archives/edgar/data/945841/000000000126000001/f4.xml',
  }],
  transactions_total: 68,
};

it('insiders: neto por periodo sin ejercicios ni regalos, compras en grupo y cada fila con su filing', () => {
  render(<InsidersSection summary={summary} ticker="POOL" />);
  const table = screen.getByRole('table');
  const rows = within(table).getAllByRole('row');
  expect(rows).toHaveLength(4);
  expect(rows[3]).toHaveTextContent('12 meses');
  expect(rows[3]).toHaveTextContent('datos desde');
  expect(rows[3]).toHaveTextContent('2 con plan 10b5-1');
  expect(screen.getByText(/No cuentan en el neto/)).toHaveTextContent('21 concesión · 11 retención fiscal · 9 regalo');
  expect(screen.getByText(/Compras en grupo/)).toBeInTheDocument();
  expect(screen.getByText(/4 insiders/)).toBeInTheDocument();
  expect(screen.getByText(/\+49,7 % de lo que tenía/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Ver Form 4' })).toHaveAttribute('href', summary.transactions[0].source_url);
  expect(screen.getByText(/0 de 49 Form 4 presentados tarde/)).toBeInTheDocument();
});

it('insiders: sin datos lo dice, no pinta ceros', () => {
  render(<InsidersSection summary={{ ...summary, status: 'sin_datos', windows: [], transactions: [] }} ticker="BN" />);
  expect(screen.getByRole('status')).toHaveTextContent('Sin operaciones de insiders guardadas para BN');
  expect(screen.queryByRole('table')).toBeNull();
});

const tickerTrades: PoliticianTickerTrades = {
  ticker: 'MSFT',
  source: 'Clerk of the House',
  status: 'ok',
  trades_total: 1,
  buys: 1,
  sells: 0,
  members: [{ member_key: 'house:OH02:taylor', member: 'David J. Taylor', party: 'R', state_district: 'OH02', buys: 1, sells: 0, last_trade: '2026-01-08' }],
  trades: [{
    owner: 'self', asset: 'Microsoft Corporation - Common Stock (MSFT)', asset_type: 'ST', ticker: 'MSFT', type: 'P', type_label: 'compra',
    tx_date: '2026-01-08', notification_date: '2026-01-15', amount_text: '$1,001 - $15,000', amount_min: 1001, amount_max: 15000,
    days_late: 0, member: 'David J. Taylor', member_key: 'house:OH02:taylor', party: 'R', state_district: 'OH02',
    filing_date: '2026-01-21', doc_id: '20033845', source_url: 'https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20033845.pdf',
  }],
};

it('políticos: quién operó el ticker, rango declarado, retraso y enlace al PTR', () => {
  render(<PoliticiansSection data={tickerTrades} ticker="MSFT" />);
  expect(screen.getByText(/1 operaciones de 1 políticos/)).toBeInTheDocument();
  expect(screen.getAllByText('OH-02').length).toBeGreaterThan(0);
  expect(screen.getByText('1.001–15.000 $')).toBeInTheDocument();
  expect(screen.getByText(/a tiempo/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Ver PTR' })).toHaveAttribute('href', tickerTrades.trades[0].source_url);
  expect(screen.getByRole('link', { name: 'Ver todos los políticos' })).toHaveAttribute('href', '/politicos');
});

it('rango abierto («Over $50,000,000») se muestra como «más de», no como una cifra', () => {
  expect(amountRange(50000001, null, 'es-ES')).toBe('> 50.000.000 $');
  expect(amountRange(null, null, 'es-ES')).toBe('—');
});

it('ficha de político: puntualidad, tarde >30 días, tickers enlazados a la ficha y volumen en rango', () => {
  render(
    <PoliticianCardView
      card={{
        member_key: 'house:MI09:mcclain', member: 'Lisa McClain', chamber: 'house', state: 'MI', district: '09', state_district: 'MI09',
        party: 'R', bioguide: null, filings: 30, scanned_filings: 1, trades: 1433, tickers: 440,
        top_tickers: [{ ticker: 'NVDA', trades: 12 }], last_trade: '2026-09-30', last_filing: '2026-10-20',
        late: 538, late_over_30: 97, on_time_pct: 62.5, volume_min: 2980433, volume_max: 25060000,
      }}
    />,
  );
  expect(screen.getByText('Republicano')).toBeInTheDocument();
  expect(screen.getByText('538 declaradas tarde, 97 más de 30 días tarde')).toBeInTheDocument();
  expect(screen.getByText('62,5 % a tiempo')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /NVDA/ })).toHaveAttribute('href', '/research/NVDA?view=seguimiento#politicos');
  expect(screen.getByText(/Volumen declarado:/)).toHaveTextContent('3');
  expect(screen.getByText('1 PTR en papel escaneado sin leer')).toBeInTheDocument();
});

it('insiders: la lista muestra primero compras y ventas en mercado', () => {
  const award = { ...summary.transactions[0], nature: 'concesion' as const, code: 'A', insider: 'OTRO', accession_number: 'x' };
  render(<InsidersSection summary={{ ...summary, transactions: [award, ...summary.transactions] }} ticker="POOL" />);
  expect(screen.getByText('Últimas compras y ventas en mercado')).toBeInTheDocument();
  expect(screen.queryByText('OTRO')).toBeNull();
});
