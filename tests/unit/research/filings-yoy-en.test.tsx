import { render, screen, within } from '@testing-library/react';
import {writeFileSync} from 'node:fs';
import { describe, expect, it, vi } from 'vitest';

const settings=vi.hoisted(()=>({locale:'en'}));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: (name: string) => (name === 'gerarai_locale' ? { value: settings.locale } : undefined) }) }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn(async () => ({ id: 'u1' })) }));
const side = (value: string) => ({ value, period: '2024', unit: 'USD', source: { url: 'https://www.sec.gov/x', published_at: null } });
vi.mock('@/lib/research/client', () => ({
  researchRequest: vi.fn(async () => ({
    status: 'ready', form: '10-K', page: 1, total: 3,
    current: { url: 'https://www.sec.gov/a', published_at: null, reported_period: '2024-12-31' },
    previous: { url: 'https://www.sec.gov/b', published_at: null, reported_period: '2023-12-31' },
    figures: [{ metric: 'revenue', unit: 'USD', current: side('1500000000'), previous: side('1000000000'), label: 'Revenue', change_pct: '50.0', highlight: true },{metric:'operating_income',unit:'EUR',current:side('12345678900'),previous:side('10000000000'),label:'Operating income',change_pct:'23.5',highlight:true}],
    text: { label: 'Item 1A', sections: [{ section: 'risk', label: 'Risk factors', status: 'changed', change_count: 1, changes: [{ kind: 'added', before: [], after: [{ text: 'New risk' }] }] }] },
  })),
}));

import {researchRequest} from '@/lib/research/client';
import FilingsYoyPage,{generateMetadata} from '@/app/(root)/research/[ticker]/filings/page';

describe('SEC report vs. prior year in English', () => {
  it('shows headings, table, changes and paging in English', async () => {
    window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
    const {container}=render(await FilingsYoyPage({ params: Promise.resolve({ ticker: 'aapl' }), searchParams: Promise.resolve({}) }));
    if(process.env.FILINGS_PREVIEW)writeFileSync('/tmp/fact-preview.html',`<!doctype html><html lang="en"><head><link rel="stylesheet" href="/style.css"></head><body class="bg-gray-950 text-gray-100"><div style="padding:16px">${container.innerHTML}</div></body></html>`);
    const card=screen.getByRole('region',{name:'Revenue'});
    expect(within(card).getAllByRole('link',{name:'SEC'})).toHaveLength(2);
    const rows=within(screen.getByRole('table')).getAllByRole('row').slice(1);
    const cards=screen.getAllByRole('region');
    rows.forEach((row,i)=>within(row).getAllByRole('cell').forEach(cell=>expect(cards[i].textContent).toContain(cell.textContent??'')));
    expect(screen.getByText('Report vs. prior year · AAPL')).toBeTruthy();
    expect(screen.getByText('Key figures')).toBeTruthy();
    expect(within(screen.getByRole('table')).getByText('Prior year')).toBeTruthy();
    expect(within(screen.getByRole('table')).getByText('+50%')).toBeTruthy();
    expect(screen.getByText('Text changes')).toBeTruthy();
    expect(screen.getByText('Added')).toBeTruthy();
    expect(screen.getByText('Now: “New risk”')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Older' })).toBeTruthy();
    expect(screen.queryByText(/Cifras clave|Año anterior|Añadido/)).toBeNull();
  });
});

it.each(['es','en'])('keeps missing sides, outflows, shares, EPS and derived sign in %s',async locale=>{
 settings.locale=locale;
 const make=(metric:string,unit:string,current:string|null,previous:string|null,change:string|null,outflow=false)=>({metric,unit,current:current===null?null:{...side(current),source:{url:'http://unsafe.invalid',published_at:null}},previous:previous===null?null:side(previous),change_pct:change,outflow,highlight:false});
 vi.mocked(researchRequest).mockResolvedValueOnce({status:'ready',current:{url:null,reported_period:null},previous:{url:null,reported_period:null},total:3,figures:[make('eps_diluted','EUR/share','1234.56','1234.56','0'),make('eps_diluted','shares','12','10','20'),make('stock_based_compensation','shares','-1234567','-1000000','-5',true),make('revenue','','123.4',null,null),make('revenue','EUR',null,'123.4',null)],text:{label:'Comparison',sections:[{section:'a',label:'Test',status:'changed',truncated:true,changes:Array.from({length:4},(_,i)=>({kind:i===0?'removed':'modified',before:[{text:'old'}],after:[{text:'new'}]}))},{section:'b',label:'Missing',status:'missing',changes:[]}]}} as never);
 render(await FilingsYoyPage({params:Promise.resolve({ticker:'brk/b'}),searchParams:Promise.resolve({form:'10-Q',page:'2'})}));
 const table=screen.getByRole('table');
 const rows=within(table).getAllByRole('row').slice(1);
 const cards=screen.getAllByRole('region');
 rows.forEach((row,i)=>within(row).getAllByRole('cell').forEach(cell=>expect(cards[i].textContent).toContain(cell.textContent??'')));
 expect(screen.getByRole('link',{name:locale==='en'?'Newer':'Más reciente'})).toHaveAttribute('href','/research/BRK%2FB/filings?form=10-Q&page=1');
 expect(document.querySelector('a[href="http://unsafe.invalid"]')).toBeNull();
});
it('metadata, failed load and ready without comparable citation remain explicit',async()=>{
 expect(await generateMetadata()).toHaveProperty('description');
 vi.mocked(researchRequest).mockRejectedValueOnce(new Error('offline'));
 const first=render(await FilingsYoyPage({params:Promise.resolve({ticker:'x'}),searchParams:Promise.resolve({page:'bogus'})}));
 expect(screen.getByRole('status')).toBeInTheDocument();first.unmount();
 vi.mocked(researchRequest).mockResolvedValueOnce({status:'ready',current:null,previous:null} as never);
 render(await FilingsYoyPage({params:Promise.resolve({ticker:'x'}),searchParams:Promise.resolve({page:'500'})}));
 expect(screen.getByRole('status')).toBeInTheDocument();
});
