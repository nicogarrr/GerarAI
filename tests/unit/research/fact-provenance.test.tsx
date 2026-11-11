import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/navigation',()=>({useRouter:()=>({refresh:vi.fn(),push:vi.fn()})}));
import { FactCard, FactTable } from '@/components/research/FactsPanels';
import type { ResearchFact } from '@/lib/actions/research.actions';
const base: ResearchFact = {id:1,company_id:1,metric:'revenue',value:'1000000',unit:'USD',period:'FY2025',fiscal_year:2025,fiscal_quarter:null,source_id:1,source_type:'SEC',is_reported:true,is_adjusted:false,confidence:'high',created_at:'2026-11-11T00:00:00Z',source_title:'Annual report 2025',source_url:'https://www.sec.gov/Archives/example.htm',source_published_at:'2026-02-15'};
describe('visible source provenance for financial facts',()=>{
 it('shows source title, provider and publication date on cards, not only a hover tooltip',()=>{
  render(<FactCard fact={base} ticker="TEST" staleness={null}/>);
  expect(screen.getByText('Annual report 2025')).toBeVisible();
  expect(screen.getByText(/Fuente: SEC/)).toBeVisible();
  expect(screen.getByText(/Publicado: 15 feb 2026/)).toBeVisible();
 });
 it('keeps source as plain text without a URL and never substitutes ingestion date for publication',()=>{
  render(<FactCard fact={{...base,source_url:null,source_published_at:null}} ticker="TEST" staleness={null}/>);
  expect(screen.getByText('Annual report 2025')).toBeVisible();
  expect(screen.getByText('Fecha de publicación no disponible')).toBeVisible();
  expect(screen.queryByRole('link')).toBeNull();
  expect(document.body.textContent).not.toContain('11 nov 2026');
 });
 it('preserves source evidence when a value is quarantined',()=>{
  render(<FactCard fact={{...base,metric:'market_cap',unit:'shares'}} ticker="TEST" staleness={null}/>);
  expect(screen.getByText(/Capitalización pendiente/)).toBeVisible();
  expect(screen.getByText('Annual report 2025')).toBeVisible();
 });
 it('shows the same source and date in desktop table rows',()=>{
  render(<FactTable facts={[base]} ticker="TEST" refreshLabel="Actualizar"/>);
  const table=within(screen.getByRole('table'));
  expect(table.getByText('Annual report 2025')).toBeInTheDocument();
  expect(table.getByText(/Publicado: 15 feb 2026/)).toBeInTheDocument();
 });
});

it('keeps missing source and invalid publication honest in English, with no ingestion timestamp',()=>{
 render(<FactCard fact={{...base,source_title:null,source_type:' ',source_url:'javascript:alert(1)',source_published_at:'invalid'}} ticker="TEST" locale="en" staleness="Latest available figure: 2020, not refreshed since"/>);
 expect(screen.getByText('Source: Not available')).toBeVisible();
 expect(screen.getByText('Publication date not available')).toBeVisible();
 expect(screen.getByText(/Latest available figure/)).toBeVisible();
 expect(screen.queryByRole('link')).toBeNull();
});
it('links a source without a title using a useful label',()=>{
 render(<FactCard fact={{...base,source_title:null}} ticker="TEST" staleness={null}/>);
 expect(screen.getByRole('link',{name:'Fuente del dato'})).toHaveAttribute('href',base.source_url);
});
it('rejects malformed and non-web URLs but preserves real document links',async()=>{
 const { factSourceUrl }=await import('@/components/research/FactSource');
 for(const value of [null,undefined,'','/relative','not url','data:text/html,test','mailto:test@example.com']) expect(factSourceUrl(value)).toBeNull();
 expect(factSourceUrl('https://example.com/report.pdf')).toBe('https://example.com/report.pdf');
 expect(factSourceUrl('http://example.com/report.pdf')).toBe('http://example.com/report.pdf');
});
it('handles an empty fact list without inventing a source',()=>{
 render(<FactTable facts={[]} ticker="TEST" refreshLabel="Actualizar"/>);
 expect(screen.getByText('Todavía no hay hechos financieros persistidos.')).toBeVisible();
 expect(screen.queryByText(/Fuente:/)).toBeNull();
});
it('retains source provenance on stale balance figures and quarantined desktop values',()=>{
 const facts=[{...base,id:1,metric:'total_debt',fiscal_year:2020,period:'FY2020'}, {...base,id:2}, {...base,id:3,metric:'market_cap',unit:'shares'}];
 render(<FactTable facts={facts} ticker="TEST" refreshLabel="Actualizar"/>);
 const table=within(screen.getByRole('table'));
 expect(table.getByText('Último dato disponible: 2020, sin refresco posterior')).toBeInTheDocument();
 expect(table.getAllByText('Annual report 2025')).toHaveLength(3);
 expect(table.getByText(/Capitalización pendiente/)).toBeInTheDocument();
});


it.each([null, 'javascript:alert(1)', '/relative', 'not a URL'])('leaves mobile and desktop values unlinked for unsafe or absent URL %s', (source_url) => {
 render(<FactTable facts={[{...base,source_url}]} ticker="TEST" refreshLabel="Actualizar"/>);
 expect(screen.queryByRole('link')).toBeNull();
 expect(screen.getAllByText('Annual report 2025')).toHaveLength(2);
});
it('links the actual mobile and desktop numbers through the validated document URL and keeps metric labels with provenance',()=>{
 render(<FactTable facts={[base]} ticker="TEST" refreshLabel="Actualizar"/>);
 // The figure link and the source-title link are separate in each surface.
 const valueLinks=screen.getAllByRole('link').filter(link=>link.textContent!=='Annual report 2025');
 expect(valueLinks).toHaveLength(2);
 for(const link of valueLinks){
  expect(link).toHaveAttribute('href',base.source_url);
  expect(link).toHaveAttribute('target','_blank');
  expect(link).toHaveAttribute('rel','noopener noreferrer');
  expect(link.textContent).not.toBe('');
 }
 const rowHeader=within(screen.getByRole('table')).getByRole('rowheader');
 expect(rowHeader).toHaveTextContent('Ingresos');
 expect(within(rowHeader).getByRole('link',{name:'Annual report 2025'})).toHaveAttribute('href',base.source_url);
});
