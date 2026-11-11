import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ThesisScenariosPanel } from '@/components/research/ThesisScenariosPanel';
import type { ThesisScenarios } from '@/lib/actions/thesis-scenarios.actions';
beforeEach(()=>{window.matchMedia=vi.fn().mockReturnValue({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()});});
const cell = (valor: number | null, motivo: string | null = null) => ({valor,etiqueta:'INFERIDO',motivo});
export const fixture: ThesisScenarios = {
 ticker:'TEST',estado:'persistido',motivo:null,fuente:{tabla:'fixture',version:3,modelo:'DCF',fecha:'2026-11-01'},aviso_coherencia:null,
 escenarios: {
  bear:{nombre:'Pesimista',motivo:null,proyecciones:[{ejercicio:2027,ingresos:cell(120000000),fcf:cell(null,'Falta el ancla FCF OFICIAL con fuente y fecha.'),bps:cell(2.12)},{ejercicio:2028,ingresos:cell(130000000),fcf:cell(12000000),bps:cell(2.5)}]},
  base:{nombre:'Central',motivo:null,proyecciones:[{ejercicio:2027,ingresos:cell(150000000),fcf:cell(15000000),bps:cell(3.24)}]},
  bull:{nombre:'Optimista',motivo:null,proyecciones:[{ejercicio:2027,ingresos:cell(180000000),fcf:cell(18000000),bps:cell(4.56)},{ejercicio:2028,ingresos:cell(190000000),fcf:cell(19000000),bps:cell(5)}]},
 },
};
describe('scenario mobile presentation',()=>{
 it('provides per-metric mobile cards, preserving every year and scenario label',()=>{
  render(<ThesisScenariosPanel data={fixture} currency="USD" adrRatio={null}/>);
  const cards=screen.getAllByRole('region',{name:/Escenarios.*202[78]/});
  expect(cards).toHaveLength(6);
  const revenue2027=within(cards[0]);
  expect(revenue2027.getByText('Pesimista')).toBeInTheDocument();
  expect(revenue2027.getByText('Central')).toBeInTheDocument();
  expect(revenue2027.getByText('Optimista')).toBeInTheDocument();
  expect(revenue2027.getByText(/120.*M.*US/)).toBeInTheDocument();
 });
 it('makes missing-data reasons visible on mobile instead of hover-only tooltips',()=>{
  render(<ThesisScenariosPanel data={fixture} currency="USD" adrRatio={null}/>);
  const cards=screen.getAllByRole('region',{name:/Escenarios.*2027/});
  expect(within(cards[1]).getByText('Falta el ancla FCF OFICIAL con fuente y fecha.')).not.toHaveClass('sr-only');
 });
});

it.each([null,{...fixture,estado:'N/D' as const},{...fixture,escenarios:{bear:{nombre:'Bear',motivo:null,proyecciones:[]},base:{nombre:'Base',motivo:null,proyecciones:[]},bull:{nombre:'Bull',motivo:null,proyecciones:[]}}}])('does not invent rows when data is unavailable',data=>{
 const view=render(<ThesisScenariosPanel data={data} currency="USD" adrRatio={null}/>);
 expect(view.container).toBeEmptyDOMElement();
});
it('keeps desktop and mobile amounts identical, without substituting missing years',()=>{
 render(<ThesisScenariosPanel data={fixture} currency="USD" adrRatio={null}/>);
 const cards=screen.getAllByRole('region',{name:/Escenarios.*2028/});
 const central=within(cards[0]).getByText('Central').closest('div');
 expect(central).toHaveTextContent('N/D');
 const tables=screen.getAllByRole('table');
 for(let metric=0;metric<tables.length;metric++){
  const rows=within(tables[metric]).getAllByRole('row').slice(1);
  rows.forEach((row,index)=>{
   const tableValues=within(row).getAllByRole('cell').map(e=>e.textContent?.trim());
   const card=screen.getAllByRole('region',{name:/Escenarios.*202[78]/})[metric*2+index];
   expect([...card.querySelectorAll('dd')].map(e=>e.textContent?.trim())).toEqual(tableValues.map(text=>text?.split(' Falta')[0]));
  });
 }
});
it('shows unverified currency and translated missing reasons on mobile in English',()=>{
 render(<ThesisScenariosPanel data={fixture} currency={null} adrRatio={null} locale="en"/>);
 const cards=screen.getAllByRole('region',{name:/5-year scenarios.*2027/});
 expect(within(cards[0]).getAllByText(/N\/A/)).toHaveLength(3);
 expect(within(cards[1]).getByText('The OFFICIAL FCF anchor with source and date is missing.')).toBeVisible();
});
it('keeps explicit backend labels and coherence warnings unchanged',()=>{
 const data=structuredClone(fixture);
 data.escenarios.bear.proyecciones[0].ingresos={valor:null,etiqueta:'PENDIENTE',motivo:null};
 data.aviso_coherencia='Aviso de coherencia del backend';
 render(<ThesisScenariosPanel data={data} currency="EUR" adrRatio={null}/>);
 expect(screen.getAllByText('PENDIENTE')).toHaveLength(2);
 expect(screen.getByText(data.aviso_coherencia)).toBeVisible();
});
