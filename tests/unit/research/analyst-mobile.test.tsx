import {render,screen,within} from '@testing-library/react';
import {expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';import {writeFileSync} from 'node:fs';
import {AnalystReportView} from '@/components/research/AnalystReportView';import {createFormatters} from '@/lib/format';import {createTranslator} from '@/lib/i18n/translate';
import type {ReportInputs} from '@/lib/research/analyst-report';import fixture from './analyst-report-asts.fixture.json';
const data:ReportInputs={...fixture as unknown as ReportInputs,card:null,fair:null,thesis:null,sotp:null,engineRange:null,consensus:{cells:[
 {metric:'revenue',period:'fy2027',period_end:'2027-12-31',status:'estimado',mid:12345678900,source:'analista_citado',citations:[{url:'https://example.com/fixture-source'}]},
 {metric:'operating_income',period:'fy2027',period_end:'2027-12-31',status:'sin_datos',reason:'Falta fuente oficial con fecha de publicación.'},
 {metric:'eps',period:'fy2027',period_end:'2027-12-31',status:'estimado',mid:1234.56,source:'guia'},
]}};
const view=()=> <AnalystReportView data={data} t={createTranslator('es')} fmt={createFormatters('es')} locale="es"/>;
it('provides complete mobile consensus rows with source links and visible missing reason',()=>{
 render(view());
 const cards=screen.getAllByRole('region',{name:/Consenso.*27/});
 expect(cards).toHaveLength(1);
 expect(within(cards[0]).getByText('Ingresos')).toBeVisible();
 expect(within(cards[0]).getByRole('link',{name:/analista/i})).toHaveAttribute('href','https://example.com/fixture-source');
 expect(within(cards[0]).getByText('Falta fuente oficial con fecha de publicación.')).toBeVisible();
});
it('optional local pixel fixture',()=>{
 if(!process.env.ANALYST_PREVIEW)return;
 writeFileSync('/tmp/fact-preview.html','<!doctype html><html class="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body style="background:#080808;color:#ddd;padding:16px">'+renderToStaticMarkup(view())+'</body></html>');
});
it('keeps formatted values and citation provenance identical in mobile cards and desktop rows',()=>{
 render(view());
 const card=screen.getByRole('region',{name:/Consenso.*27/});
 const table=within(screen.getByTestId('informe-consensus')).getByRole('table');
 const cells=within(table).getAllByRole('cell');
 for(const cell of cells)expect(card.textContent).toContain(cell.textContent??'');
 const a=within(card).getByRole('link');
 const b=within(table).getByRole('link');
 expect(a.getAttribute('href')).toBe(b.getAttribute('href'));
});
