import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
const mocks=vi.hoisted(()=>({push:vi.fn(),refresh:vi.fn(),change:vi.fn()}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:mocks.push,refresh:mocks.refresh})}));
import StrategySelector from '@/components/proPicks/StrategySelector';
const value=(id:string,name:string)=>({id,name,description:`Descripción de ${name}`});
const server=[value('growth','Crecimiento'),value('future','Futura')];
const catalog=[value('growth','Nombre catálogo'),value('value','Valor')];
beforeEach(()=>vi.clearAllMocks());
describe('ProPicks strategy selector',()=>{
 it('has a stable accessible name and shows only selected strategy name while closed',()=>{
  render(<StrategySelector strategies={server} currentStrategy="growth" catalog={catalog}/>);
  const trigger=screen.getByRole('combobox',{name:'Estrategia'});
  expect(trigger).toHaveTextContent('Crecimiento');expect(trigger).not.toHaveTextContent('Descripción');
 });
 it('keeps unavailable catalog choices and additional server strategies selectable',async()=>{
  render(<StrategySelector strategies={server} currentStrategy="growth" catalog={catalog} onStrategyChange={mocks.change}/>);
  fireEvent.keyDown(screen.getByRole('combobox'),{key:'ArrowDown'});
  expect(await screen.findByRole('option',{name:/Valor.*Sin datos/})).toBeVisible();
  expect(screen.getByRole('option',{name:/Futura/})).toBeVisible();
  fireEvent.click(screen.getByRole('option',{name:/Valor.*Sin datos/}));
  await waitFor(()=>expect(mocks.push).toHaveBeenCalledWith('/propicks?strategy=value'));
  expect(mocks.change).toHaveBeenCalledWith('value');expect(mocks.refresh).toHaveBeenCalledOnce();
 });
 it.each([undefined,[]])('uses server choices when catalog is %s',async catalog=>{
  render(<StrategySelector strategies={server} currentStrategy="growth" catalog={catalog}/>);
  fireEvent.keyDown(screen.getByRole('combobox'),{key:'ArrowDown'});
  fireEvent.click(await screen.findByRole('option',{name:/Futura/}));
  expect(mocks.push).toHaveBeenCalledWith('/propicks?strategy=future');expect(mocks.refresh).toHaveBeenCalledOnce();
 });
 it('handles unknown current strategy without falsely naming a selected choice',()=>{
  render(<StrategySelector strategies={[]} currentStrategy="unknown"/>);
  expect(screen.getByRole('combobox',{name:'Estrategia'})).not.toHaveTextContent('Crecimiento');
 });
});
