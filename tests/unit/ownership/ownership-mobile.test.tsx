import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {writeFileSync} from 'node:fs';
import { ExternalAPIError } from '@/lib/types/errors';
import {mobileHoldings,mobileChanges} from '../../fixtures/ownership-mobile';
const mocks=vi.hoisted(()=>({locale:'es',managers:vi.fn(),holdings:vi.fn(),changes:vi.fn()}));
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>({value:mocks.locale})})}));
vi.mock('@/lib/actions/ownership.actions',()=>({getOwnershipManagers:mocks.managers,getManagerHoldings:mocks.holdings,getManagerChanges:mocks.changes}));
vi.mock('@/app/(root)/ownership/SyncButton',()=>({default:()=>null}));
vi.mock('@/app/(root)/inversores/_components/SyncPortfoliosButton',()=>({SyncPortfoliosButton:()=>null}));
vi.mock('@/app/(root)/ownership/_components/MostBought',()=>({MostBought:()=> <p>Most bought fixture</p>}));
vi.mock('@/app/(root)/ownership/_components/Overlap',()=>({Overlap:()=> <p>Overlap fixture</p>}));
import OwnershipPage, {generateMetadata} from '@/app/(root)/ownership/page';
// Tabla responsiva única (2026-11-14): las filas de datos son <tr> con aria-label
// (antes: tarjetas <article> duplicadas con la tabla escritorio).
const dataRows=()=>screen.queryAllByRole('row').filter(r=>r.getAttribute('aria-label'));
beforeEach(()=>{mocks.locale='es';mocks.managers.mockReset().mockResolvedValue({managers:[{cik:'1',name:'Fixture Fund'}],limitations:[]});mocks.holdings.mockReset().mockResolvedValue(structuredClone(mobileHoldings));mocks.changes.mockReset().mockResolvedValue(structuredClone(mobileChanges));});
it('shows labelled mobile holding cards with CUSIP, amendment, declared class and filing',async()=>{
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 const cards=dataRows();
 expect(cards).toHaveLength(2);
 const holding=within(cards[0]);
 expect(holding.getByText('123456789')).toBeVisible();
 expect(holding.getByText('CLASS A COMMON STOCK')).toBeVisible();
 expect(holding.getByText(/enmienda/)).toBeVisible();
 expect(holding.getByRole('link',{name:/XML/})).toHaveAttribute('href','https://example.com/fixture-13f.xml');
});
it('keeps comparison report dates and values attached to their previous/current labels',async()=>{
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 const change=within(dataRows()[1]);
 expect(change.getByText('123456789')).toBeVisible();
 expect(change.getByText('100.000')).toBeVisible();
 expect(change.getByText('123.456')).toBeVisible();
 expect(change.getByText(/1 mil/)).toBeVisible();
 expect(change.getByText(/1,25 M/)).toBeVisible();
});
it('optional local pixel fixture',async()=>{
 if(!process.env.OWNERSHIP_PREVIEW)return;
 writeFileSync('/tmp/fact-preview.html','<!doctype html><html class="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body style="background:#080808;color:#ddd;padding:16px">'+renderToStaticMarkup(await OwnershipPage({searchParams:Promise.resolve({})}))+'</body></html>');
});

it('keeps nullable snapshot fields honest and shows no filing link when absent',async()=>{
 mocks.holdings.mockResolvedValue({...mobileHoldings,manager:null,report_date:null,coverage:null,provenance:{fetched_at:'2026-11-01',source:'fixture'},holdings:[{...mobileHoldings.holdings[0],name_of_issuer:null,title_of_class:null,cusip:null,put_call:'PUT',share_type:null,shares:null,value_usd_thousands:null,is_amendment:false,filing_url:null}]});
 mocks.changes.mockResolvedValue({...mobileChanges,previous_report:null,latest_report:null,changes:[{...mobileChanges.changes[0],name_of_issuer:null,cusip:null,shares_previous:null,shares_latest:null,value_usd_thousands_previous:null,value_usd_thousands_latest:null,change:'backend-new-code'}]});
 render(await OwnershipPage({searchParams:Promise.resolve({cik:'1'})}));
 const cards=dataRows();
 expect(within(cards[0]).queryByRole('link')).toBeNull();
 expect(within(cards[0]).getByText('PUT')).toBeVisible();
 expect(within(cards[0]).getAllByText('N/D').length).toBeGreaterThan(3);
 expect(within(cards[1]).getByText('backend-new-code')).toBeVisible();
 expect(within(cards[1]).getAllByText('N/D').length).toBeGreaterThan(3);
});
it('keeps unchanged rows out of both mobile and desktop movement lists',async()=>{
 mocks.changes.mockResolvedValue({...mobileChanges,changes:[{...mobileChanges.changes[0],change:'unchanged'}]});
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 expect(dataRows()).toHaveLength(1);
 expect(screen.getByText(/Sin movimientos entre/)).toBeVisible();
});
it('handles missing names, absent type and verified holdings without warning',async()=>{
 mocks.holdings.mockResolvedValue({...mobileHoldings,status:'ok',holdings:[{...mobileHoldings.holdings[0],share_type:null,put_call:null,filing_url:null,is_amendment:false}]});
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 expect(within(dataRows()[0]).getAllByText('N/D').length).toBeGreaterThan(0);
 expect(screen.queryByText(/cifras sin verificar/)).toBeNull();
});
it('renders empty managers without fake holdings',async()=>{
 mocks.managers.mockResolvedValue({managers:[],limitations:['Fixture limitation']});
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 expect(dataRows()).toHaveLength(0);
 expect(screen.getByText('Fixture limitation')).toBeInTheDocument();
});
it.each(['mas-compradas','solape'])('preserves alternate view %s without fetching a manager',async vista=>{
 render(await OwnershipPage({searchParams:Promise.resolve({vista})}));
 expect(mocks.holdings).not.toHaveBeenCalled();
 expect(screen.getByText(vista==='solape'?'Overlap fixture':'Most bought fixture')).toBeVisible();
});
it('preserves source metadata title generation',async()=>{
 expect(await generateMetadata()).toMatchObject({title:'Propiedad institucional (13F)'});
});
it('keeps unavailable changes distinct from insufficient history',async()=>{
 mocks.changes.mockResolvedValue({...mobileChanges,status:'unavailable'});
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 expect(dataRows()).toHaveLength(1);
});
it.each(['managers','holdings','changes'] as const)('shows backend offline when %s cannot be read',async key=>{
 mocks[key].mockRejectedValue(new ExternalAPIError('fetch failed','research'));
 render(await OwnershipPage({searchParams:Promise.resolve({cik:'1'})}));
 expect(dataRows()).toHaveLength(0);
});
it('does not swallow a programming error in the essential managers read',async()=>{
 const error=new Error('programming defect');mocks.managers.mockRejectedValue(error);
 await expect(OwnershipPage({searchParams:Promise.resolve({})})).rejects.toBe(error);
});
it('handles non-network optional errors without fabricating rows',async()=>{
 mocks.holdings.mockRejectedValue(new Error('denied'));
 mocks.changes.mockRejectedValue(new Error('denied'));
 render(await OwnershipPage({searchParams:Promise.resolve({cik:'1'})}));
 expect(dataRows()).toHaveLength(0);
});
it('keeps English mobile labels and formatted values in the single responsive rows',async()=>{
 mocks.locale='en';
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 const rows=dataRows();
 expect(rows).toHaveLength(2);
 // Cada valor aparece UNA vez por fila (antes iba duplicado: tarjeta + tabla).
 expect(within(rows[0]).getAllByText('123456789')).toHaveLength(1);
 expect(within(rows[0]).getByText('Shares')).toBeInTheDocument();
 expect(within(rows[1]).getByText('Shares before')).toBeInTheDocument();
 expect(within(rows[1]).getByText('Value now')).toBeInTheDocument();
});
