import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import DcaHitRatesPopover from '@/components/watchlist/DcaHitRatesPopover';
import type {DcaHitRates} from '@/lib/dca/types';
const mocks=vi.hoisted(()=>({load:vi.fn()}));
vi.mock('@/lib/actions/dca-signals.actions',()=>({getDcaHitRates:mocks.load}));
const data=(over:Partial<DcaHitRates>={}):DcaHitRates=>({symbol:'TEST',available:true,reason:null,months_completed:12,first_period:'2025-01',last_period:'2025-12',horizons:[1,3],params_version:'v1',evaluated_at:null,disclaimer:'Solo histórico.',rows:[{key:'2x',label:'2X',levels:[2],color:'#FFFFFF',signal_months:4,cells:[{horizon_months:1,months:4,pct_higher:0.75,avg_return:0.10},{horizon_months:3,months:0,pct_higher:null,avg_return:null}]}],...over});
beforeEach(()=>vi.clearAllMocks());
describe('DCA historical evidence display',()=>{
 it('distinguishes unavailable from a specific no-history reason',()=>{
  const view=render(<DcaHitRatesCard data={null}/>);expect(screen.getByText('Histórico de señales no disponible ahora mismo.')).toBeVisible();
  view.rerender(<DcaHitRatesCard data={data({available:false,reason:'No hay meses confirmados'})}/>);expect(screen.getByText('No hay meses confirmados')).toBeVisible();
  view.rerender(<DcaHitRatesCard data={data({available:false})}/>);expect(screen.getByText('Aún sin histórico de señales para este ticker.')).toBeVisible();
 });
 it('renders period, sample size and missing values without inventing performance',()=>{
  render(<DcaHitRatesCard data={data()}/>);
  expect(screen.getByRole('table')).toHaveAccessibleName('Porcentaje de meses con señal cuyo cierre era más alto N meses después');
  expect(screen.getByText(/12 meses completados/)).toHaveTextContent('2025-01');
  expect(screen.getByText('75,0 %')).toBeVisible();expect(screen.getByText(/n=4/)).toHaveTextContent('media 10,0 %');
  expect(screen.getByText('—')).toBeVisible();expect(screen.getByText(/Solo meses confirmados/)).toHaveTextContent('no la rentabilidad de una cartera');
 });
 it.each([null,'red','#000000','#FFFFFF'])('supports contrasting badge color %s and compact mode',color=>{
  const fixture=data();fixture.first_period=null;fixture.rows[0].color=color;
  render(<DcaHitRatesCard data={fixture} compact/>);
  expect(screen.queryByText(/n=4/)).not.toBeInTheDocument();
  expect(screen.getByText('2X')).toHaveStyle({color:color==='#000000'?'#FFFFFF':'#111827'});
 });
 it('loads only on demand, reports loading and caches a successful response',async()=>{
  let resolve!:(d:DcaHitRates)=>void;mocks.load.mockReturnValue(new Promise(r=>resolve=r));
  render(<DcaHitRatesPopover symbol="TEST"/>);expect(mocks.load).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Histórico de señales DCA de TEST'}));
  expect(await screen.findByText('Cargando histórico…')).toBeVisible();expect(mocks.load).toHaveBeenCalledWith('TEST');
  await act(async()=>resolve(data()));expect(await screen.findByTestId('dca-hit-rates')).toBeVisible();
  fireEvent.keyDown(screen.getByRole('dialog'),{key:'Escape'});
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole('button',{name:'Histórico de señales DCA de TEST'}));
  expect(await screen.findByTestId('dca-hit-rates')).toBeVisible();expect(mocks.load).toHaveBeenCalledOnce();
 });
 it('retries on reopen after an unavailable or failed load instead of caching it',async()=>{
  mocks.load.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(null).mockResolvedValueOnce(data());
  render(<DcaHitRatesPopover symbol="TEST"/>);
  const trigger=()=>screen.getByRole('button',{name:'Histórico de señales DCA de TEST'});
  const close=async()=>{fireEvent.keyDown(screen.getByRole('dialog'),{key:'Escape'});await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());};
  fireEvent.click(trigger());
  expect(await screen.findByText('Histórico de señales no disponible ahora mismo.')).toBeVisible();
  await close();fireEvent.click(trigger());
  expect(await screen.findByText('Histórico de señales no disponible ahora mismo.')).toBeVisible();
  await close();fireEvent.click(trigger());
  expect(await screen.findByTestId('dca-hit-rates')).toBeVisible();
  expect(mocks.load).toHaveBeenCalledTimes(3);
 });
 it('shows unavailable when the action returns null',async()=>{
  mocks.load.mockResolvedValue(null);render(<DcaHitRatesPopover symbol="TEST"/>);
  fireEvent.click(screen.getByRole('button',{name:'Histórico de señales DCA de TEST'}));
  expect(await screen.findByText('Histórico de señales no disponible ahora mismo.')).toBeVisible();
 });
});
