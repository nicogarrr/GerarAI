import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const getPlan = vi.fn();
const getSavingsProjection = vi.fn();
vi.mock('@/lib/actions/plan.actions', () => ({ getPlan: (...args: unknown[]) => getPlan(...args), getSavingsProjection: (...args: unknown[]) => getSavingsProjection(...args) }));
vi.mock('@/components/plan/PlanSetupDialog', () => ({default: ({triggerLabel,onSaved}: {triggerLabel: string;onSaved?:()=>void}) => <button onClick={onSaved}>{triggerLabel}</button>}));
vi.mock('next/link', () => ({default: ({children, href}: {children: React.ReactNode; href: string}) => <a href={href}>{children}</a>}));
import SavingsProjection from '@/components/portfolio/SavingsProjection';
const scenario = {years:20,annual_total_return:.05,contributed:240000,terminal_value:405804.49,simulated_return:165804.49,terminal_value_today_money:273093.84,annual_inflation:.02,terminal_dividend_yield:.03,terminal_annual_gross_dividend:12174.13,terminal_monthly_gross_dividend_equivalent:1014.51,net_dividend:null};
const projection = {plan_exists:true,preview:false,monthly_contribution:1000,currency:'EUR',horizon_years:20,initial_capital:0,portfolio_included:false,status:'ok',scenarios:[scenario],assumptions:[]};
beforeEach(()=>{getPlan.mockReset().mockResolvedValue({plan_exists:true,monthly_contribution:1000});getSavingsProjection.mockReset().mockResolvedValue(projection)});
describe('SavingsProjection',()=>{
 it('lee el plan común y distingue aportaciones de valoración, sin órdenes',async()=>{
  render(<SavingsProjection/>);
  expect((await screen.findAllByText(/405.804,49/)).length).toBeGreaterThan(0);
  expect(screen.getByText('Editar mi plan')).toBeInTheDocument();
  expect(screen.getByRole('link',{name:/reparto de la aportación/})).toHaveAttribute('href','/plan');
  expect(screen.queryByText(/no modifica tu aportación guardada/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', {name:'Simular sin guardar'})).toBeInTheDocument();
  expect(getPlan).toHaveBeenCalledTimes(1);
  expect(getSavingsProjection).toHaveBeenCalledTimes(1);
 });
 it('preview explícito no guarda y marca cambios aún no recalculados',async()=>{
  render(<SavingsProjection/>);await screen.findAllByText(/405.804,49/);
  fireEvent.change(screen.getByLabelText('Aportación mensual'),{target:{value:'500'}});
  expect(screen.getByText(/Has cambiado los campos/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Simular sin guardar'}));
  await waitFor(()=>expect(getSavingsProjection).toHaveBeenLastCalledWith({monthly:500,years:20,currency:'EUR',dividendYield:.03,inflation:.02}));
 });
 it('guardar el plan vuelve a leer el mismo contrato para Cerebro y DCA',async()=>{
  render(<SavingsProjection/>);await screen.findAllByText(/405.804,49/);
  fireEvent.click(screen.getByText('Editar mi plan'));
  await waitFor(()=>expect(getPlan).toHaveBeenCalledTimes(2));
  expect(getSavingsProjection).toHaveBeenCalledTimes(2);
 });
 it('entrada ambigua usa el aviso canónico y no llama al servidor',async()=>{
  render(<SavingsProjection/>);await screen.findAllByText(/405.804,49/);
  fireEvent.change(screen.getByLabelText('Aportación mensual'),{target:{value:'1,234'}});
  fireEvent.click(screen.getByRole('button',{name:'Simular sin guardar'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Formato de número ambiguo: usa la coma');
  expect(getSavingsProjection).toHaveBeenCalledTimes(1);
 });
 it('sin divisa no inventa resultados, permite un preview explícito',async()=>{
  getSavingsProjection.mockResolvedValue({...projection,status:'currency_missing',currency:null,scenarios:[]});
  render(<SavingsProjection/>);
  expect(await screen.findByText(/no tiene divisa registrada/)).toBeInTheDocument();
  expect(screen.queryByText(/405.804/)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Divisa de la aportación')).toHaveValue('');
  fireEvent.click(screen.getByRole('button',{name:'Simular sin guardar'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Elige la divisa');
  expect(getSavingsProjection).toHaveBeenCalledTimes(1);
 });
 it('fallo no se convierte en cero ni borra el estado anterior',async()=>{
  render(<SavingsProjection/>);await screen.findAllByText(/405.804,49/);
  getSavingsProjection.mockRejectedValueOnce(new Error('x'));
  fireEvent.click(screen.getByRole('button',{name:'Simular sin guardar'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Conservamos el resultado anterior');
  expect(screen.getAllByText(/405.804,49/).length).toBeGreaterThan(0);
 });
 it('editar durante una simulación no marca el resultado anterior como actualizado',async()=>{
  render(<SavingsProjection/>);await screen.findAllByText(/405.804,49/);
  let resolve!: (value: typeof projection) => void;
  getSavingsProjection.mockReturnValueOnce(new Promise(r=>{resolve=r}));
  fireEvent.change(screen.getByLabelText('Aportación mensual'),{target:{value:'500'}});
  fireEvent.click(screen.getByRole('button',{name:'Simular sin guardar'}));
  fireEvent.change(screen.getByLabelText('Divisa de la aportación'),{target:{value:'USD'}});
  resolve({...projection,monthly_contribution:500});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Simular sin guardar'})).toBeEnabled());
  expect(screen.getByLabelText('Divisa de la aportación')).toHaveValue('USD');
  expect(screen.getByRole('status')).toHaveTextContent('Has cambiado los campos');
 });

});
