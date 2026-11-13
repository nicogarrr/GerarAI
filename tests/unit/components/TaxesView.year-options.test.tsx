import {renderToString} from 'react-dom/server';
import {writeFileSync} from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/taxes.actions', () => ({
    regenerateTaxReport: vi.fn(), getTaxReport: vi.fn(), getTaxHoldings: vi.fn(), previewTaxFiling: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
import TaxesView from '@/components/taxes/TaxesView';


const props={initialHoldings:[],initialReport:null,initialThresholds720:null,initialFile720:null,year:2026};
describe('TaxesView · selector de ejercicio',()=>{
 it('incluye el ejercicio recibido en HTML del servidor antes de hidratar',()=>{
  const html=renderToString(<TaxesView {...props}/>);
  const root=document.createElement('div');root.innerHTML=html;
  const select=root.querySelector<HTMLSelectElement>('#tax-year');
  expect(select?.value).toBe('2026');
  expect(select?.selectedOptions[0].textContent).toBe('2026');
  expect(select?.options).toHaveLength(1);
  if(process.env.TAX_YEAR_PREVIEW) writeFileSync('/tmp/tax-year-ssr.html','<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/tmp/tax-year-style.css"></head><body style="background:#080808;color:#ddd;padding:16px">'+html+'</body></html>');
 });
 it('conserva un ejercicio antiguo fuera de la ventana de seis años',()=>{
  render(<TaxesView {...props} year={2000}/>);
  const select=screen.getByRole('combobox',{name:'Ejercicio'}) as HTMLSelectElement;
  expect(select.value).toBe('2000');
  expect(select.selectedOptions[0].textContent).toBe('2000');
  const values=[...select.options].map(o=>Number(o.value));
  expect(new Set(values).size).toBe(values.length);
  expect(values).toEqual([...values].sort((a,b)=>b-a));
 });
 it('no duplica el ejercicio actual después de hidratar',()=>{
  const year=Number(new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Madrid',year:'numeric'}).format(new Date()));
  render(<TaxesView {...props} year={year}/>);
  const select=screen.getByRole('combobox',{name:'Ejercicio'}) as HTMLSelectElement;
  expect(select.value).toBe(String(year));
  expect([...select.options].filter(o=>o.value===String(year))).toHaveLength(1);
  expect(select.options).toHaveLength(6);
 });
});
