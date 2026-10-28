import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
const mocks=vi.hoisted(()=>({doc:vi.fn(),collection:vi.fn(),router:{refresh:vi.fn()}}));
vi.mock('@/lib/actions/research-tools.actions',()=>({deleteKnowledgeDocument:mocks.doc,deleteKnowledgeCollection:mocks.collection}));
vi.mock('next/navigation',()=>({useRouter:()=>mocks.router}));
import {DeleteDocumentButton} from '@/components/knowledge/DeleteDocumentButton';
import {DeleteCollectionButton} from '@/components/knowledge/DeleteCollectionButton';
import {ExtractionRefresh} from '@/components/knowledge/ExtractionRefresh';
beforeEach(()=>vi.clearAllMocks());afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();});
for(const kind of ['document','collection'] as const)describe(`library ${kind} delete confirmation`,()=>{
 const view=()=>kind==='document'?<DeleteDocumentButton documentId={987} title="Documento de prueba"/>:<DeleteCollectionButton collectionId={765} name="Colección de prueba"/>;
 const action=()=>kind==='document'?mocks.doc:mocks.collection;
 const open=()=>fireEvent.click(screen.getByRole('button',{name:/^Eliminar (documento|colección):/}));
 it('cancels without sending a delete and names the destructive target',()=>{
  render(view());open();const dialog=screen.getByRole('dialog');
  expect(dialog).toHaveAccessibleName(kind==='document'?'¿Eliminar «Documento de prueba»?':'¿Eliminar la colección vacía «Colección de prueba»?');
  expect(within(dialog).getByText(/no se puede deshacer/)).toBeVisible();
  fireEvent.click(within(dialog).getByRole('button',{name:'Cancelar'}));expect(action()).not.toHaveBeenCalled();
 });
 it('waits for confirmation and disables the trigger during deletion',async()=>{
  let resolve!:(v:unknown)=>void;action().mockReturnValue(new Promise(r=>resolve=r));
  render(view());expect(action()).not.toHaveBeenCalled();open();
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Eliminar',exact:true}));
  expect(action()).toHaveBeenCalledWith(kind==='document'?987:765);
  expect(screen.getByRole('button',{name:/^Eliminar (documento|colección):/})).toBeDisabled();expect(screen.getByText('Eliminando...')).toBeVisible();
  await act(async()=>resolve({success:true}));expect(screen.getByRole('button')).toBeEnabled();expect(screen.queryByRole('alert')).not.toBeInTheDocument();
 });
 it('shows a failed delete and allows a later successful retry',async()=>{
  action().mockResolvedValueOnce({success:false}).mockResolvedValueOnce({success:true});render(view());open();
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Eliminar',exact:true}));
  expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo eliminar. Inténtalo de nuevo.');
  open();fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Eliminar',exact:true}));
  await waitFor(()=>expect(screen.queryByRole('alert')).not.toBeInTheDocument());expect(action()).toHaveBeenCalledTimes(2);
 });
});
describe('extraction refresh lifecycle',()=>{
 it('does nothing when inactive',async()=>{vi.useFakeTimers();render(<ExtractionRefresh active={false}/>);await act(async()=>vi.advanceTimersByTimeAsync(180000));expect(mocks.router.refresh).not.toHaveBeenCalled();});
 it('backs off from 30s to 60s and cancels on completion',async()=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');const view=render(<ExtractionRefresh active/>);
  await act(async()=>vi.advanceTimersByTimeAsync(29999));expect(mocks.router.refresh).not.toHaveBeenCalled();
  await act(async()=>vi.advanceTimersByTimeAsync(1));expect(mocks.router.refresh).toHaveBeenCalledTimes(1);
  await act(async()=>vi.advanceTimersByTimeAsync(60000));expect(mocks.router.refresh).toHaveBeenCalledTimes(2);
  view.rerender(<ExtractionRefresh active={false}/>);await act(async()=>vi.advanceTimersByTimeAsync(120000));expect(mocks.router.refresh).toHaveBeenCalledTimes(2);
 });
 it('skips hidden tabs and removes its timer on unmount',async()=>{
  vi.useFakeTimers();const visibility=vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');const view=render(<ExtractionRefresh active/>);
  await act(async()=>vi.advanceTimersByTimeAsync(30000));expect(mocks.router.refresh).not.toHaveBeenCalled();visibility.mockReturnValue('visible');
  await act(async()=>vi.advanceTimersByTimeAsync(30000));expect(mocks.router.refresh).toHaveBeenCalledOnce();view.unmount();await act(async()=>vi.advanceTimersByTimeAsync(120000));expect(mocks.router.refresh).toHaveBeenCalledOnce();
 });
});
