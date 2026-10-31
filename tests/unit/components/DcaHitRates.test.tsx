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
 it('muestra el tiempo medio en 2X-4X solo con visitas completadas y declara la abierta',()=>{
  const zone_visits={available:true,reason:null,levels:[2,3,4],months_completed:130,first_period:'2015-01',last_period:'2026-09',completed_visits:2,avg_months:2.5,max_months:3,visits:[{start:'2018-06',end:'2018-08',months:3},{start:'2019-01',end:'2019-02',months:2}],open_visit_months:1,params_version:'v1'};
  render(<DcaHitRatesCard data={data({zone_visits})}/>);
  expect(screen.getByTestId('dca-zone-visits')).toHaveTextContent('Tiempo medio en 2X-4X: 2,5 meses · 2 visitas completadas · en curso 1 m (no cuenta)');
 });
 it('declara las visitas excluidas por huecos con su n, sin contarlas en la media',()=>{
  const zone_visits={available:true,reason:null,levels:[2,3,4],months_completed:130,first_period:'2015-01',last_period:'2026-09',completed_visits:2,excluded_gap_visits:1,avg_months:2.5,max_months:3,visits:[{start:'2018-06',end:'2018-08',months:3},{start:'2019-01',end:'2019-02',months:2}],open_visit_months:null,params_version:'v1'};
  const view=render(<DcaHitRatesCard data={data({zone_visits})}/>);
  expect(screen.getByTestId('dca-zone-visits')).toHaveTextContent('2 visitas completadas · 1 excluida por huecos en el histórico');
  view.rerender(<DcaHitRatesCard data={data({zone_visits:{...zone_visits,excluded_gap_visits:3}})}/>);
  expect(screen.getByTestId('dca-zone-visits')).toHaveTextContent('3 excluidas por huecos');
 });
 it('no inventa el tiempo medio: sin dato o sin visitas completadas se dice y no se muestra cifra',()=>{
  const view=render(<DcaHitRatesCard data={data()}/>);
  expect(view.container.querySelector('[data-testid="dca-zone-visits"]')).toBeNull();
  const zero={available:true,reason:null,levels:[2,3,4],months_completed:8,first_period:'2025-01',last_period:'2025-08',completed_visits:0,avg_months:null,max_months:null,visits:[],open_visit_months:null,params_version:'v1'};
  view.rerender(<DcaHitRatesCard data={data({zone_visits:zero})}/>);
  expect(screen.getByTestId('dca-zone-visits')).toHaveTextContent('Sin visitas completadas a 2X-4X en el histórico');
  expect(screen.getByTestId('dca-zone-visits')).not.toHaveTextContent('meses ·');
 });
 it('etiqueta cada celda con su horizonte para que en movil no se pierda ninguna columna',()=>{
  const four=data({horizons:[1,3,6,12]});
  four.rows=four.rows.map(r=>({...r,cells:[1,3,6,12].map((h,i)=>({horizon_months:h,months:4-i,pct_higher:0.5+i*0.1,avg_return:0.01}))}));
  render(<DcaHitRatesCard data={four}/>);
  // cabecera de escritorio (1) + una etiqueta movil por fila (1 fila) = 2 por horizonte
  for(const h of ['1 m','3 m','6 m','12 m']) expect(screen.getAllByText(h)).toHaveLength(2);
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
