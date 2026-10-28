import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
const mocks=vi.hoisted(()=>({save:vi.fn(),refresh:vi.fn(),success:vi.fn(),error:vi.fn()}));
vi.mock('next/navigation',()=>({useRouter:()=>({refresh:mocks.refresh})}));
vi.mock('sonner',()=>({toast:{success:mocks.success}}));
vi.mock('@/lib/toast',()=>({showErrorToast:mocks.error}));
vi.mock('@/lib/actions/dca-signals.actions',()=>({setDcaAlertMinLevel:mocks.save}));
import DcaMinLevelSelect from '@/components/watchlist/DcaMinLevelSelect';
async function choose(name:string){
 const trigger=screen.getByRole('combobox');
 fireEvent.keyDown(trigger,{key:'ArrowDown'});
 fireEvent.click(await screen.findByRole('option',{name}));
}
beforeEach(()=>vi.clearAllMocks());
describe('DCA alert minimum level control',()=>{
 it('uses global label and accessible ticker name',()=>{
  render(<DcaMinLevelSelect symbol="TEST" override={null} globalMinLevel={3}/>);
  expect(screen.getByRole('combobox',{name:'Nivel mínimo de aviso DCA para TEST'})).toHaveTextContent('Global (3X)');
 });
 it('persists numeric override and blocks further changes until confirmation',async()=>{
  let resolve!:(v:unknown)=>void;mocks.save.mockReturnValue(new Promise(r=>{resolve=r}));
  render(<DcaMinLevelSelect symbol="TEST" override={null} globalMinLevel={2}/>);
  await choose('4X');
  expect(mocks.save).toHaveBeenCalledWith('TEST',4);
  expect(screen.getByRole('combobox')).toBeDisabled();
  await act(async()=>resolve({success:true}));
  expect(screen.getByRole('combobox')).toBeEnabled();
  expect(screen.getByRole('combobox')).toHaveTextContent('4X');
  expect(mocks.success).toHaveBeenCalledWith('Avisos DCA de TEST: 4X');
  expect(mocks.refresh).toHaveBeenCalledOnce();
 });
 it('returns to global with null, never a numeric sentinel',async()=>{
  mocks.save.mockResolvedValue({success:true});
  render(<DcaMinLevelSelect symbol="TEST" override={1} globalMinLevel={2}/>);
  await choose('Global (2X)');
  await waitFor(()=>expect(mocks.refresh).toHaveBeenCalledOnce());
  expect(mocks.save).toHaveBeenCalledWith('TEST',null);
  expect(screen.getByRole('combobox')).toHaveTextContent('Global (2X)');
 });
 it.each([undefined,'Servidor no disponible'])('rolls back unsuccessful save (%s)',async(message)=>{
  mocks.save.mockResolvedValue({success:false,message});
  render(<DcaMinLevelSelect symbol="TEST" override={1} globalMinLevel={2}/>);
  await choose('4X');
  await waitFor(()=>expect(mocks.error).toHaveBeenCalledWith(message??'No se pudo guardar el nivel de aviso'));
  expect(screen.getByRole('combobox')).toHaveTextContent('1X');
  expect(screen.getByRole('combobox')).toBeEnabled();
  expect(mocks.refresh).not.toHaveBeenCalled();expect(mocks.success).not.toHaveBeenCalled();
 });
 it('rolls back thrown request and permits retry',async()=>{
  const error=Error('Offline');mocks.save.mockRejectedValueOnce(error).mockResolvedValueOnce({success:true});
  render(<DcaMinLevelSelect symbol="TEST" override={1} globalMinLevel={2}/>);
  await choose('4X');await waitFor(()=>expect(mocks.error).toHaveBeenCalledWith(error));
  expect(screen.getByRole('combobox')).toHaveTextContent('1X');
  await choose('4X');await waitFor(()=>expect(mocks.refresh).toHaveBeenCalledOnce());
  expect(mocks.save).toHaveBeenCalledTimes(2);
 });
});
