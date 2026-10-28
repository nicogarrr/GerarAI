import {act,render,screen} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
const mocks=vi.hoisted(()=>({router:{refresh:vi.fn()}}));
vi.mock('next/navigation',()=>({useRouter:()=>mocks.router}));
import ProPicksLoadError from '@/components/proPicks/ProPicksLoadError';
import {BackendOfflineAutoRetry} from '@/components/system/BackendOfflineAutoRetry';
beforeEach(()=>vi.clearAllMocks());afterEach(()=>vi.useRealTimers());
describe('ProPicks request error states',()=>{
 it.each([401,403])('offers sign-in only for a session/access error %s',statusCode=>{
  render(<ProPicksLoadError statusCode={statusCode}/>);
  expect(screen.getByRole('alert')).toHaveTextContent('No se pudo acceder a la selección con esta sesión.');
  expect(screen.getByRole('link',{name:'Iniciar sesión'})).toHaveAttribute('href','/sign-in');
  expect(screen.getByRole('link',{name:'Reintentar'})).toHaveAttribute('href','/propicks');
 });
 it.each([
  [429,'La consulta ha alcanzado el límite de solicitudes.'],
  [404,'No se pudo completar esta consulta de ProPicks.'],
  [500,'Puede ser un fallo temporal de esta lectura.'],
  [undefined,'Puede ser un fallo temporal de esta lectura.'],
 ])('keeps failure classification scoped to the request (%s)',(statusCode,message)=>{
  render(<ProPicksLoadError statusCode={statusCode}/>);
  expect(screen.getByRole('alert')).toHaveTextContent(message!);
  expect(screen.queryByRole('link',{name:'Iniciar sesión'})).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).not.toHaveTextContent(/motor.*desconectado|sin selecci[oó]n publicada/i);
 });
});
describe('bounded backend automatic retry',()=>{
 it('retries at 5, 10, 20 and 40 seconds then stops',async()=>{
  vi.useFakeTimers();render(<BackendOfflineAutoRetry/>);
  for(const [i,delay] of [5000,10000,20000,40000].entries()){
   expect(screen.getByRole('status')).toHaveTextContent(`intento ${i+1} de 4`);
   await act(async()=>vi.advanceTimersByTimeAsync(delay-1));expect(mocks.router.refresh).toHaveBeenCalledTimes(i);
   await act(async()=>vi.advanceTimersByTimeAsync(1));expect(mocks.router.refresh).toHaveBeenCalledTimes(i+1);
  }
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  await act(async()=>vi.advanceTimersByTimeAsync(300000));expect(mocks.router.refresh).toHaveBeenCalledTimes(4);
 });
 it('cancels its pending retry after recovery/unmount',async()=>{
  vi.useFakeTimers();const view=render(<BackendOfflineAutoRetry/>);await act(async()=>vi.advanceTimersByTimeAsync(4999));view.unmount();
  await act(async()=>vi.advanceTimersByTimeAsync(300000));expect(mocks.router.refresh).not.toHaveBeenCalled();
 });
});
