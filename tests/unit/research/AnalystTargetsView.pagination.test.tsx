import { fireEvent,render,screen } from '@testing-library/react';
import { describe,expect,it } from 'vitest';
import { AnalystTargetsView } from '@/components/research/AnalystTargetsView';
import type { components } from '@/lib/research/openapi.generated';
const data={status:'available',currency:'USD',consensus:{median:78,mean:74,low:42,high:108},rows:Array.from({length:7},(_,i)=>({firm:`Firm ${i+1}`,date:'2026-10-23',price_target:55,prior_target:50,rating:'Buy',upside_percent:10})),source:'Yahoo Finance',source_url:null,fetched_at:1793120400,reference_price:50} as components['schemas']['AnalystTargets'];
describe('analyst pagination by firm',()=>{
 it('shows five firms, next/back is bounded and consensus stays visible',()=>{
  render(<AnalystTargetsView data={data}/>);
  expect(screen.getAllByText('Firm 1')).toHaveLength(2);
  expect(screen.queryByText('Firm 6')).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Anterior'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Siguiente'}));
  expect(screen.queryByText('Firm 1')).not.toBeInTheDocument();
  expect(screen.getAllByText('Firm 6')).toHaveLength(2);
  expect(screen.getByRole('button',{name:'Siguiente'})).toBeDisabled();
  expect(screen.getByText(/Consenso agregado de Yahoo: mediana/)).toBeInTheDocument();
  expect(screen.queryByText('Recorrido')).not.toBeInTheDocument();
  expect(screen.getAllByText('Potencial').length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button',{name:'Anterior'}));
  expect(screen.getAllByText('Firm 1')).toHaveLength(2);
 });
});
