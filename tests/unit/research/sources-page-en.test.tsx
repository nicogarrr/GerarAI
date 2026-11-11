import React from 'react';
import { writeFileSync } from 'node:fs';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import { Pager } from '@/components/research/Pager';

const i18n = vi.hoisted(() => ({ locale: 'en' as 'es' | 'en' }));
vi.mock('@/lib/i18n/server', async () => {
    const { createTranslator } = await import('@/lib/i18n/translate');
    return { getLocale: async () => i18n.locale, getT: async () => createTranslator(i18n.locale) };
});
vi.mock('@/lib/actions/research.actions', () => ({
    getResearchSources: vi.fn(async () => ({
        documents: [{ id: 1, ticker: 'AAPL', title: '10-K 2025', source_type: 'filing', source_tier: 'tier_1_regulatory', published_at: null, source_url: 'https://www.sec.gov/x' }],
        audits: [], documentsTotal: 1, pageInfo: { page: 1, pages: 1, from: 1, to: 1 },
    })),
    importResearchDocumentFile: vi.fn(), importResearchDocumentUrl: vi.fn(), importResearchSource: vi.fn(),
}));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => null }));
vi.mock('@/components/forms/FileUploadInputLazy', () => ({ FileUploadInputLazy: () => null }));
vi.mock('@/components/forms/MutationForm', () => ({ MutationForm: ({ children }: { children: React.ReactNode }) => <form>{children}</form> }));
import { AppError } from '@/lib/types/errors';
import { getResearchSources } from '@/lib/actions/research.actions';
import ResearchSourcesPage, { generateMetadata } from '@/app/(root)/research/sources/page';

const page = () => ResearchSourcesPage({ searchParams: Promise.resolve({}) } as never);

describe('fuentes y paginador en inglés', () => {
    it('la página de fuentes sale en inglés', async () => {
        i18n.locale = 'en';
        const {container}=render(await page());
        if(process.env.SOURCES_PREVIEW) writeFileSync('/tmp/fact-preview.html',`<!doctype html><html lang="en"><head><link rel="stylesheet" href="/style.css"></head><body class="bg-gray-950 text-gray-100"><div style="padding:16px">${container.innerHTML}</div></body></html>`);
        const card=screen.getByRole('region',{name:'AAPL · 10-K 2025'});
        expect(within(card).getByText('no date')).toBeInTheDocument();
        expect(within(card).getByRole('link',{name:/Open/})).toHaveAttribute('href','https://www.sec.gov/x');
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Sources');
        expect(screen.getAllByText('Regulatory filing').length).toBeGreaterThan(1);
        expect(screen.getAllByText('no date')).toHaveLength(2);
        expect(screen.getByText('No audits yet.')).toBeInTheDocument();
        expect(screen.getByText('Add sources')).toBeInTheDocument();
        expect(screen.queryByText(/Documentos|Auditorías|Añadir fuentes|sin fecha/)).not.toBeInTheDocument();
    });
    it('en español no cambia', async () => {
        i18n.locale = 'es';
        render(await page());
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Fuentes');
        expect(screen.getAllByText('Documento regulatorio').length).toBeGreaterThan(0);
        expect(screen.getByText('Sin auditorías todavía.')).toBeInTheDocument();
    });
    it('el paginador compartido sigue el idioma', () => {
        render(<LocaleProvider locale="en"><Pager label="documents" onPage={() => undefined} page={1} pages={3} total={30} /></LocaleProvider>);
        expect(screen.getByRole('navigation', { name: 'Pagination: documents' })).toBeInTheDocument();
        expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument();
    });
    it('el paginador en español no cambia', () => {
        render(<Pager label="documentos" onPage={() => undefined} page={2} pages={3} total={30} />);
        expect(screen.getByRole('navigation', { name: 'Paginación de documentos' })).toBeInTheDocument();
        expect(screen.getByText('Página 2 de 3')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Anterior' })).toBeInTheDocument();
    });
});

describe('source cards parity and page branches',()=>{
 it.each(['es','en'] as const)('cards preserve source/date/tier/title and missing URL in %s',async locale=>{
  i18n.locale=locale;
  const documents=[
   {id:1,ticker:'ABC',title:'Official release',source_type:'sec',source_tier:'tier_1_regulatory',published_at:'2026-06-01',source_url:'https://example.com/fixture'},
   {id:2,ticker:null,title:'Unknown source',source_type:'new_unknown',source_tier:'tier_3',published_at:null,source_url:null},
  ];
  vi.mocked(getResearchSources).mockResolvedValueOnce({documents,audits:[{id:1,passed:false,source_coverage_score:50,required_fixes:['Missing valuation inputs: market_cap.']},{id:2,passed:true,source_coverage_score:100,required_fixes:[]}],documentsTotal:20,pageInfo:{page:2,pages:3,from:11,to:20}} as never);
  render(await ResearchSourcesPage({searchParams:Promise.resolve({ticker:'ABC',scope:'all',q:'release',source_type:'sec',page:'2'})}));
  const cards=documents.map(d=>screen.getByRole('region',{name:`${d.ticker??'GLOBAL'} · ${d.title}`}));
  const rows=screen.getAllByRole('row').slice(1);
  rows.forEach((row,i)=>within(row).getAllByRole('cell').forEach(cell=>expect(cards[i].textContent).toContain(cell.textContent??'')));
  expect(within(cards[1]).queryByRole('link')).toBeNull();
  const prev=screen.getByRole('link',{name:locale==='en'?'Previous':'Anterior'});
  expect(prev.getAttribute('href')).not.toContain('page=2');
  expect(prev.getAttribute('href')).toContain('ticker=ABC');
 });
 it.each([{ticker:'ABC'}, {scope:'followed'}, {scope:'all'}, {scope:'all',q:'missing'}])('keeps empty state recovery links %j',async params=>{
  i18n.locale='en';
  vi.mocked(getResearchSources).mockResolvedValueOnce({documents:[],audits:[],documentsTotal:null,pageInfo:null} as never);
  render(await ResearchSourcesPage({searchParams:Promise.resolve(params)}));
  expect(screen.queryByRole('region',{name:/ · /})).toBeNull();
  expect(screen.getByRole('table')).toBeInTheDocument();
 });
 it('shows audit count limit and source count fallback with no publication date substitution',async()=>{
  i18n.locale='en';
  vi.mocked(getResearchSources).mockResolvedValueOnce({documents:[{id:3,ticker:'ABC',title:'No date',source_type:'url',source_tier:'unknown',published_at:null,source_url:null}],audits:Array.from({length:9},(_,id)=>({id,passed:true,source_coverage_score:100,required_fixes:[]})),documentsTotal:null,pageInfo:{page:1,pages:3,from:1,to:1}} as never);
  render(await ResearchSourcesPage({searchParams:Promise.resolve({page:'-1'})}));
  expect(screen.getAllByText('no date')).toHaveLength(2);
  expect(screen.getAllByText('passed')).toHaveLength(8);
 });
});

it('metadata title is translated',async()=>{expect(await generateMetadata()).toHaveProperty('title');});
it('backend offline preserves filters but other errors propagate',async()=>{
 vi.mocked(getResearchSources).mockRejectedValueOnce(new AppError('offline','EXTERNAL_API_ERROR'));
 const offline=await ResearchSourcesPage({searchParams:Promise.resolve({ticker:'ABC',scope:'all',q:'test'})});
 expect(offline.props.retryHref).toContain('ticker=ABC');
 expect(offline.props.retryHref).toContain('q=test');
 const error=new Error('not offline');
 vi.mocked(getResearchSources).mockRejectedValueOnce(error);
 await expect(page()).rejects.toBe(error);
});
