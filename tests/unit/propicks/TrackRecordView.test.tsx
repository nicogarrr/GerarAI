import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import type {TrackRecordPick,TrackRecordResponse} from '@/lib/actions/propicks-track-record.actions';
const mocks=vi.hoisted(()=>({load:vi.fn()}));
vi.mock('@/lib/actions/propicks-track-record.actions',()=>({getTrackRecord:mocks.load}));
import TrackRecordView from '@/components/proPicks/TrackRecordView';
const pick=(over:Partial<TrackRecordPick>={}):TrackRecordPick=>({ticker:'TEST',name:'Synthetic',currency:'EUR',entry_month:'2026-01',entry_price:100,entry_price_date:'2026-01-02',status:'activo',exit_month:null,exit_price:null,exit_price_date:null,exit_pct:null,spy_pct_exit:null,current_price:110,current_price_date:'2026-10-27',current_stale:false,pct_since_entry:0.1,spy_pct_since_entry:0.02,horizon_date:'2026-04-02',pct_90d:null,spy_pct_90d:null,...over});
const data=(picks:TrackRecordPick[]=[],over:Partial<TrackRecordResponse>={}):TrackRecordResponse=>({snapshots_count:1,history_label:'Histórico corto',months:['2026-01'],stale_threshold_days:7,horizon_days:90,spy:{available:true,source:'local-fixture',latest_date:'2026-10-27'},picks,...over});
beforeEach(()=>vi.clearAllMocks());
describe('ProPicks track record display',()=>{
 it('blocks refresh during load then shows honest empty state',async()=>{
  let resolve!:(v:unknown)=>void;mocks.load.mockReturnValue(new Promise(r=>resolve=r));render(<TrackRecordView/>);
  await waitFor(()=>expect(mocks.load).toHaveBeenCalledOnce());expect(screen.getByRole('button',{name:'Actualizar'})).toBeDisabled();
  await act(async()=>resolve(data([],{snapshots_count:0})));
  expect(await screen.findByText('Aún no hay histórico')).toBeVisible();expect(screen.queryByRole('table')).not.toBeInTheDocument();expect(screen.getByRole('button')).toBeEnabled();
 });
 it('shows action error and recovers on explicit refresh',async()=>{
  mocks.load.mockResolvedValueOnce({error:'No disponible'}).mockResolvedValueOnce(data([],{snapshots_count:0}));render(<TrackRecordView/>);
  expect(await screen.findByText('No disponible')).toBeVisible();fireEvent.click(screen.getByRole('button',{name:'Actualizar'}));
  expect(await screen.findByText('Aún no hay histórico')).toBeVisible();expect(screen.queryByText('No disponible')).not.toBeInTheDocument();
 });
 it('shows active, exited and stale records with same-window SPY and missing values',async()=>{
  mocks.load.mockResolvedValue(data([
   pick(),
   pick({ticker:'EXIT',status:'salio',exit_month:'2026-05',exit_price:80,exit_price_date:'2026-05-02',exit_pct:-0.2,spy_pct_exit:0,pct_90d:0.03}),
   pick({ticker:'STALE',current_stale:true,current_price_date:'2026-02-03',pct_since_entry:null,spy_pct_since_entry:null,entry_price:null}),
  ]));render(<TrackRecordView/>);
  const table=await screen.findByRole('table');expect(table).toHaveAccessibleName(/Track record de selecciones ProPicks/);
  const row=within(table).getByRole('row',{name:/^TEST/});expect(row).toHaveTextContent('activo');expect(row).toHaveTextContent('+10,0 %');expect(row).toHaveTextContent('SPY +2,0 %');expect(row).toHaveTextContent('pendiente');
  expect(within(table).getByRole('row',{name:/^EXIT/})).toHaveTextContent('-20,0 %');expect(within(table).getByRole('row',{name:/^STALE/})).toHaveTextContent('sin dato actual');
  expect(screen.getByText(/SPY \(local-fixture\)/)).toBeVisible();expect(screen.getByText(/Histórico corto/)).toBeVisible();
 });
 it('does not invent exit/current prices or SPY when unavailable',async()=>{
  mocks.load.mockResolvedValue(data([
   pick({ticker:'EXIT',status:'salio',currency:null,entry_price:null,exit_price:null,exit_pct:null,horizon_date:null}),
   pick({ticker:'ZERO',current_price:null,pct_since_entry:0,horizon_date:null}),
  ],{spy:{available:false,source:'',latest_date:null}}));render(<TrackRecordView/>);
  expect(await screen.findByText('sin precio de salida')).toBeVisible();expect(screen.getByText(/Serie de SPY sin datos todavía/)).toBeVisible();
  expect(screen.queryByText(/pendiente \(/)).not.toBeInTheDocument();expect(within(screen.getByRole('row',{name:/^ZERO/})).getByText('0,0 %')).toBeVisible();
 });
});
