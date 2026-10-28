import {render,screen,within} from '@testing-library/react';
import {describe,expect,it} from 'vitest';
import StrategyFactsheet from '@/components/proPicks/StrategyFactsheet';
import type {WalkForwardBacktestResult} from '@/lib/actions/propicks-backtest.actions';
const props={strategyId:'adaptive',name:'Estrategia de prueba',description:'Descripción explícita',available:true};
// Optional/absent fields model old persisted payloads, not a backend calculation.
const fixture=(over:Record<string,unknown>={}):WalkForwardBacktestResult=>({retornoNeto:12,spy:8,sharpe:1.5,maxDD:-4,turnover:20,tablaMensual:[{asOf:'2026-01-31'},{asOf:'2026-02-28'}],...over} as unknown as WalkForwardBacktestResult);
describe('strategy factsheet honest performance display',()=>{
 it('unavailable catalog strategy shows no selection or performance promise',()=>{
  render(<StrategyFactsheet {...props} available={false}/>);expect(screen.getByText('Sin datos')).toBeVisible();expect(screen.getByText(/no hay selección ni métricas/)).toBeVisible();expect(screen.queryByText('Retorno neto')).not.toBeInTheDocument();
 });
 it('shows pending state only without an existing backtest',()=>{
  render(<StrategyFactsheet {...props} loading/>);expect(screen.getByText('Calculando métricas de Estrategia de prueba…')).toBeVisible();
 });
 it('shows real rulebook instead of invented performance when no global baseline exists',()=>{
  render(<StrategyFactsheet {...props}/>);expect(screen.getByText('Sin métricas de desempeño')).toBeVisible();expect(screen.getByText('Qué decide esta estrategia')).toBeVisible();expect(screen.getByText('Valoración')).toBeVisible();expect(screen.getByText(/No se sustituye por una estimación/)).toBeVisible();
 });
 it('unknown strategy still exposes error without inventing a rulebook',()=>{
  render(<StrategyFactsheet {...props} strategyId="not-defined" error="Sin servicio"/>);expect(screen.getByRole('alert')).toHaveTextContent('Sin servicio');expect(screen.queryByText('Qué decide esta estrategia')).not.toBeInTheDocument();
 });
 it('labels baseline as global and shows supplied point-valued metrics',()=>{
  render(<StrategyFactsheet {...props} backtest={fixture()} loading error="Old error"/>);
  expect(screen.getByText('Backtest global, no de la estrategia')).toBeVisible();expect(screen.queryByText('Old error')).not.toBeInTheDocument();
  for(const [label,value] of [['Retorno neto','+12,00 %'],['SPY (referencia)','+8,00 %'],['Sharpe neto','1,50'],['Caída máxima neta','-4,00 %'],['Rotación media','20 %']]){
   const cell=screen.getByText(label).parentElement!;expect(cell).toHaveTextContent(value);
  }
  expect(screen.getByText(/Período:/)).not.toHaveTextContent('Sin dato');
 });
 it('does not fabricate absent metrics or period in an older payload',()=>{
  render(<StrategyFactsheet {...props} backtest={fixture({spy:null,sharpe:null,maxDD:null,turnover:null,tablaMensual:[]})}/>);
  expect(screen.getAllByText('Sin dato').length).toBeGreaterThanOrEqual(5);
  expect(within(screen.getByText('Exceso vs SPY').parentElement!).getByText('Sin dato')).toBeVisible();expect(screen.getByText(/Período:/)).toHaveTextContent('Sin dato');
 });
 it('rejects malformed baseline payload as absent, never as zero returns',()=>{
  render(<StrategyFactsheet {...props} backtest={fixture({retornoNeto:undefined})}/>);expect(screen.getByText('Sin métricas de desempeño')).toBeVisible();expect(screen.queryByText('Retorno neto')).not.toBeInTheDocument();
 });
});
