import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
const m=vi.hoisted(()=>({approve:vi.fn(),refresh:vi.fn(),success:vi.fn(),warning:vi.fn(),info:vi.fn(),error:vi.fn()}));
vi.mock('next/navigation',()=>({useRouter:()=>({refresh:m.refresh})}));
vi.mock('@/lib/actions/thesis-jobs.actions',()=>({approveThesis:m.approve}));
vi.mock('sonner',()=>({toast:{success:m.success,warning:m.warning,info:m.info}}));
vi.mock('@/lib/toast',()=>({showErrorToast:m.error}));
vi.mock('@/lib/utils/scroll-anchor',()=>({preserveScrollPosition:(run:()=>void)=>run()}));
import ThesisApproveButton from '@/components/research/ThesisApproveButton';
beforeEach(()=>vi.clearAllMocks());
describe('manual thesis approval controls',()=>{
 it.each(['insufficient_data','draft_failed_audit'])('blocks nonapprovable version %s but permits rejection',status=>{
  render(<ThesisApproveButton ticker="TEST" latestStatus={status} latestVersion={3}/>);
  expect(screen.getByRole('button',{name:'Aprobar tesis'})).toBeDisabled();expect(screen.getByText(/La v3 no se puede publicar/)).toBeVisible();expect(screen.getByRole('button',{name:'Rechazar'})).toBeEnabled();
 });
 it('blocks absent versions and identifies an already published version',()=>{
  const v=render(<ThesisApproveButton ticker="TEST" disabled/>);expect(screen.getByText('Sin versiones de tesis que aprobar o rechazar.')).toBeVisible();expect(screen.getByRole('button',{name:'Rechazar'})).toBeDisabled();
  v.rerender(<ThesisApproveButton ticker="TEST" latestStatus="published" latestVersion={4}/>);expect(screen.getByRole('button',{name:'Publicada v4'})).toBeDisabled();
 });
 it.each(['indexed','unchanged','failed',undefined])('reports actual library indexing outcome %s',async status=>{
  m.approve.mockResolvedValue({decision:'approved',version:3,knowledge_sync:status?{status}:undefined});render(<ThesisApproveButton ticker="TEST"/>);
  fireEvent.click(screen.getByRole('button',{name:'Aprobar tesis'}));await waitFor(()=>expect(m.refresh).toHaveBeenCalledOnce());
  expect(m.approve).toHaveBeenCalledWith('TEST','approved');
  if(status==='failed')expect(m.warning).toHaveBeenCalledWith('Tesis v3 aprobada, pero no se pudo indexar en la Biblioteca');
  else expect(m.success).toHaveBeenCalledWith(status==='indexed'?'Tesis v3 aprobada y añadida a la Biblioteca':status==='unchanged'?'Tesis v3 aprobada; ya estaba en la Biblioteca':'Tesis v3 aprobada');
 });
 it('requires explicit confirmation of risk and can cancel without side effects',async()=>{
  m.approve.mockResolvedValue({decision:'approved',version:3});render(<ThesisApproveButton ticker="TEST" riskNotes={['Faltan fuentes']}/>);
  fireEvent.click(screen.getByRole('button',{name:'Aprobar tesis'}));expect(screen.getByRole('alert')).toHaveTextContent('Faltan fuentes');expect(m.approve).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Cancelar'}));expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Aprobar tesis'}));fireEvent.click(screen.getByRole('button',{name:'Publicar igualmente'}));await waitFor(()=>expect(m.refresh).toHaveBeenCalledOnce());
 });
 it.each(['removed',undefined])('rejection reports removal honestly and preserves older publication (%s)',async status=>{
  m.approve.mockResolvedValue({decision:'rejected',version:3,knowledge_sync:status?{status}:undefined});render(<ThesisApproveButton ticker="TEST" olderPublishedVersion={2}/>);
  fireEvent.click(screen.getByRole('button',{name:'Rechazar'}));await waitFor(()=>expect(m.refresh).toHaveBeenCalledOnce());
  expect(m.success).toHaveBeenCalledWith(status==='removed'?'Tesis v3 rechazada y retirada de la Biblioteca':'Tesis v3 rechazada');expect(m.info).toHaveBeenCalledWith('La v2 sigue publicada: rechazar solo afecta a la última versión.');
 });
 it('blocks both decisions while pending and allows failed request retry',async()=>{
  let reject!:(e:Error)=>void;const error=Error('Offline');m.approve.mockReturnValueOnce(new Promise((_,r)=>reject=r)).mockResolvedValueOnce({decision:'rejected',version:3});
  render(<ThesisApproveButton ticker="TEST"/>);fireEvent.click(screen.getByRole('button',{name:'Rechazar'}));expect(screen.getByRole('button',{name:'Rechazando…'})).toBeDisabled();expect(screen.getByRole('button',{name:'Aprobar tesis'})).toBeDisabled();
  await act(async()=>reject(error));expect(m.error).toHaveBeenCalledWith(error,{onRetry:expect.any(Function)});expect(m.refresh).not.toHaveBeenCalled();
  await act(async()=>m.error.mock.calls[0][1].onRetry());expect(m.refresh).toHaveBeenCalledOnce();expect(m.info).not.toHaveBeenCalled();
 });
});
