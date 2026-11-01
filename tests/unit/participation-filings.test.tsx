import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
beforeEach(() => { window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })); });
import { ParticipationFilingsPanel } from '@/components/research/ParticipationFilingsPanel';
import { participationNumber, participationSource } from '@/lib/research/schedule13dg';
const filing = { accession_number: '0002100119-26-001548', form: 'SCHEDULE 13G', holder_name: 'Vanguard Capital Management', aggregate_shares: 15330194, percent_of_class: 5.11, snapshot_date: '2026-09-30', filing_date: '2026-10-30', source_url: 'https://www.sec.gov/Archives/edgar/data/1780312/000210011926001548/primary_doc.xml', status: 'parsed' };
describe('participation filing display', () => {
  it('preserves percentages and null vs zero', () => {
    expect(participationNumber(5.11, true)).toBe('5,11 %');
    expect(participationNumber(0)).toBe('0');
    expect(participationNumber(null)).toBe('N/D');
    expect(participationNumber(NaN)).toBe('N/D');
  });
  it('validates links', () => {
    expect(participationSource(filing.source_url)).toBe(filing.source_url);
    for (const url of [null, 'not a url', 'javascript:alert(1)', 'https://sec.gov.evil/Archives/edgar/data/x', 'http://sec.gov/Archives/edgar/data/x', 'https://sec.gov/not-edgar']) expect(participationSource(url)).toBeNull();
  });
  it('shows dates, values, source and scope disclaimer', () => {
    render(<ParticipationFilingsPanel data={{ ticker: 'ASTS', count: 1, filings: [filing] }} />);
    expect(screen.getByText(/Vanguard Capital Management/)).toBeTruthy();
    expect(screen.getByText(/15.330.194 acciones · 5,11 %/)).toBeTruthy();
    expect(screen.getByText('Posición a 2026-09-30')).toBeTruthy();
    expect(screen.getByText('Presentado 2026-10-30')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Documento SEC' }).getAttribute('href')).toBe(filing.source_url);
    expect(screen.getByText(/no operaciones de compra o venta/)).toBeTruthy();
  });
  it('empty does not imply no ownership', () => {
    render(<ParticipationFilingsPanel data={{ ticker: 'ASTS', count: 0, filings: [] }} />);
    expect(screen.getByText(/Esto no demuestra ausencia/)).toBeTruthy();
  });
  it('unavailable is distinct', () => {
    render(<ParticipationFilingsPanel data={null} />);
    expect(screen.getByText(/No se pudieron cargar/)).toBeTruthy();
  });
  it('unparsed fields and unsafe source stay honest', () => {
    render(<ParticipationFilingsPanel data={{ ticker: 'ASTS', count: 1, filings: [{ ...filing, holder_name: null, aggregate_shares: null, percent_of_class: null, snapshot_date: null, filing_date: null, source_url: 'https://evil.example', status: 'unparsed' }] }} />);
    expect(screen.getByText(/Declarante N\/D/)).toBeTruthy();
    expect(screen.getByText(/pendiente de lectura completa/)).toBeTruthy();
    expect(screen.queryByRole('link')).toBeNull();
  });
});
