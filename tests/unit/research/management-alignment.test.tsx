import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ManagementAlignmentSection } from '@/components/research/sections/ManagementAlignmentSection';
import { alignmentNumber, alignmentUrl, type AlignmentEvidence, type AlignmentWindow, type AlignmentYear, type ManagementAlignment } from '@/lib/research/management-alignment';
import { writeFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@/lib/research/client', () => ({ researchRequest: vi.fn().mockResolvedValue({ status: 'pendiente' }) }));
afterEach(cleanup);
const fact: AlignmentEvidence = { fact_id: 1, metric: 'stock_based_compensation', value: 120, unit: 'USD', date: '2025-12-31', filed: '2026-02-01', url: 'https://example.com/filing' };
const ratio = { value: 12, sources: [fact, { ...fact, fact_id: 2, metric: 'revenue' }] };
const year: AlignmentYear = { year: 2025, shares: { ...fact, metric: 'shares_outstanding', unit: 'shares', value: 108.2 }, share_basis: 'shares_outstanding', shares_change_pct: { value: 8.2, sources: [fact] }, sbc: fact, sbc_revenue_pct: ratio, sbc_fcf_pct: { value: null, reason: 'Falta caja operativa.' }, repurchases: null, repurchases_label: 'Recompras (bruto)', change_label: 'Variación de acciones', warnings: [], quality_warnings: [] };
const trade = { code: 'S', plan: true, value: 100, date: '2026-10-01', url: 'https://example.com/form4', accession: 'A', form: '4' };
const win: AlignmentWindow = { months: 12, from: '2025-11-11', to: '2026-11-11', status: 'ok', reason: '', groups: { buys: [{ ...trade, code: 'P', plan: null }], planned_sales: [trade], unplanned_sales: [], unknown_sales: [] }, net_value: 0, discretionary_net_value: 100, warnings: [] };
const data: ManagementAlignment = { status: 'ok', ticker: 'AAPL', as_of: '2026-11-11', computed_at: '2026-11-11T15:00:00Z', years: [year], insiders: [win] };

describe('alignment concise read-only evidence', () => {
  it('keeps linked figures but removes source labels, boilerplate and unavailable rows', () => {
    render(<ManagementAlignmentSection data={data} />);
    expect(screen.getAllByRole('link', { hidden: true, name: '120,0 USD' }).length).toBeGreaterThan(0);
    expect(screen.queryByText(/SBC \/ flujo de caja libre:/)).toBeNull();
    expect(screen.queryByText(/Recompras \(bruto\):/)).toBeNull();
    expect(screen.queryByText(/publicado|Operaciones y fuentes|Datos disponibles para tu análisis/)).toBeNull();
    expect(screen.queryByText(/N\/D/)).toBeNull();
    expect(screen.getAllByText(/Cobertura parcial:/)).toHaveLength(1);
    expect(screen.getByText(/Flujo sin ventas programadas:/)).toHaveTextContent('100,0 USD');
    expect(screen.getByText(/Bajo plan: 1/).closest('a')).toHaveAttribute('href', trade.url);
    expect(screen.getByText(/Ejercicio 2025/)).toHaveTextContent('2025-12-31');
    for (const a of screen.getAllByRole('link', { hidden: true })) {
      expect(a).toHaveAttribute('target', '_blank'); expect(a).toHaveAttribute('rel', 'noopener noreferrer');
    }
    expect(document.querySelectorAll('details[open]')).toHaveLength(0);
  });
  it('preserves cause-specific pending, no-data and stale warnings without fake zero', () => {
    const view = render(<ManagementAlignmentSection data={{ status: 'pendiente', ticker: 'AENA.MC', reason: 'El job no ha corrido.' }} />);
    expect(screen.getByRole('status')).toHaveTextContent('El job no ha corrido.');
    view.rerender(<ManagementAlignmentSection data={{ ...data, stale: true, years: [], dilution_reason: 'No hay hechos anuales persistidos.', insiders: [{ ...win, status: 'sin_datos', reason: 'No hay P/S persistidas.', groups: { buys: [], planned_sales: [], unplanned_sales: [], unknown_sales: [] } }] }} />);
    expect(screen.getByText(/Datos desactualizados/)).toBeInTheDocument();
    expect(screen.getByText('No hay hechos anuales persistidos.')).toBeInTheDocument();
    expect(screen.getByText('No hay P/S persistidas.')).toBeInTheDocument();
    expect(screen.queryByText('0,0 USD')).toBeNull();
  });
  it('hides unsafe figure/ratio links and preserves one incomplete-flow notice per window', () => {
    render(<ManagementAlignmentSection data={{ ...data, years: [{ ...year, shares: { ...fact, url: 'javascript:alert(1)' }, sbc: null, shares_change_pct: { value: 12, sources: [] }, sbc_revenue_pct: { value: 10, sources: [{ ...fact, url: '/relative' }] } }], insiders: [{ ...win, net_value: null, discretionary_net_value: null, groups: { ...win.groups, buys: [], unknown_sales: [{ ...trade, plan: null, value: null, url: null }], planned_sales: [] } }] }} />);
    expect(screen.queryByText(/Flujo sin ventas programadas:/)).toBeNull();
    expect(screen.getAllByText(/Flujo incompleto:/)).toHaveLength(1);
    for (const a of document.querySelectorAll('a')) expect(a.href).not.toContain('javascript:');
  });
  it.each(['shares_diluted', 'dei'])('makes the alternative share basis %s explicit', basis => {
    render(<ManagementAlignmentSection data={{ ...data, years: [{ ...year, share_basis: basis }] }} />);
    expect(screen.getByText(basis === 'dei' ? /Acciones en la fecha de portada:/ : /Promedio ponderado diluido:/)).toBeInTheDocument();
  });
  it('keeps reported zero buybacks, valid FCF ratio and abnormal-data warnings', () => {
    render(<ManagementAlignmentSection data={{ ...data, years: [{ ...year, sbc_fcf_pct: ratio, repurchases: { ...fact, value: 0 }, quality_warnings: ['Variación abrupta: revisar.'] }] }} />);
    expect(screen.getByText(/Recompras \(bruto\):/)).toHaveTextContent('0,0 USD');
    expect(screen.getByText(/SBC \/ flujo de caja libre:/)).toHaveTextContent('12,0 %');
    expect(screen.getByText(/Variación abrupta: revisar./)).toBeInTheDocument();
  });
  it('handles optional blocks, missing dates and unsafe trade links', () => {
    const view = render(<ManagementAlignmentSection data={{ status: 'ok', ticker: 'X' }} />);
    view.rerender(<ManagementAlignmentSection data={{ ...data, years: [{ ...year, shares: null, sbc: null, quality_warnings: undefined, repurchases: null, shares_change_pct: { value: null }, warnings: [] }], insiders: [{ ...win, groups: { buys: [], planned_sales: [], unplanned_sales: [], unknown_sales: [{ ...trade, plan: null, value: null, url: 'javascript:x' }] } }] }} />);
    expect(screen.getByText('Compras: 0').closest('span')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Compras: 0', hidden: true })).toBeNull();
    view.rerender(<ManagementAlignmentSection data={{ ...data, years: [{ ...year, shares: null, sbc: null, repurchases: fact }] }} />);
    expect(screen.getByText(/Ejercicio 2025/)).toHaveTextContent('2025-12-31');
  });
  it('keeps an implausible reported amount visible with a review warning', () => {
    render(<ManagementAlignmentSection data={{ ...data, insiders: [{ ...win, warnings: ['Importe inválido.'], groups: { ...win.groups, unknown_sales: [{ ...trade, plan: null, value: null, reported_value: '-1' }] } }] }} />);
    expect(screen.getByText('Importe reportado -1 USD: revisar.')).toHaveAttribute('href', trade.url);
  });
  it('formats Spanish one-decimal numbers and accepts only full HTTP URLs', () => {
    expect(alignmentNumber(1.25, '%')).toBe('1,3 %'); expect(alignmentNumber(-12.1)).toBe('-12,1');
    expect(alignmentUrl(null)).toBeNull(); expect(alignmentUrl('bad')).toBeNull();
    expect(alignmentUrl('javascript:x')).toBeNull(); expect(alignmentUrl('http://example.com')).toBe('http://example.com');
  });
  it('reads the isolated endpoint and encodes ticker', async () => {
    const { getManagementAlignment } = await import('@/lib/actions/management-alignment.actions');
    const { researchRequest } = await import('@/lib/research/client');
    await getManagementAlignment('BRK/B');
    expect(researchRequest).toHaveBeenCalledWith('/api/companies/BRK%2FB/management-alignment', { fast: true });
  });
  it('exports actual markup for pixel verification', () => {
    writeFileSync('/tmp/alignment-preview.html', renderToStaticMarkup(<ManagementAlignmentSection data={data} />));
  });
});
