import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
const m=vi.hoisted(()=>({create:vi.fn(),success:vi.fn(),error:vi.fn(),info:vi.fn(),showError:vi.fn()}));
vi.mock('@/lib/actions/alerts.actions',()=>({createAlertResult:m.create}));
vi.mock('sonner',()=>({toast:{success:m.success,error:m.error,info:m.info}}));
vi.mock('@/lib/toast',()=>({showErrorToast:m.showError}));
import QuickAlertButton from '@/components/research/QuickAlertButton';
async function open(){fireEvent.click(screen.getByRole('button',{name:'Alerta de precio'}));await screen.findByRole('combobox',{name:'Tipo de alerta'});}
async function type(label:string){fireEvent.keyDown(screen.getByRole('combobox',{name:'Tipo de alerta'}),{key:'ArrowDown'});fireEvent.click(await screen.findByRole('option',{name:label}));}
beforeEach(()=>vi.clearAllMocks());
describe('quick research alert',()=>{
 it.each(['','0','-1','abc'])('rejects invalid/nonpositive input %s before any action',async value=>{
  render(<QuickAlertButton ticker="TEST" currency="EUR"/>);await open();fireEvent.change(screen.getByRole('textbox',{name:'Precio objetivo en EUR'}),{target:{value}});fireEvent.click(screen.getByRole('button',{name:'+ Alerta'}));
  expect(m.error).toHaveBeenCalledWith('Introduce un precio objetivo válido');expect(m.create).not.toHaveBeenCalled();
 });
 it('sends localized decimal and below operator, then clears only after success',async()=>{
  m.create.mockResolvedValue({ok:true});render(<QuickAlertButton ticker="TEST" currency="EUR" compact/>);await open();await type('Precio por debajo de');
  const input=screen.getByRole('textbox',{name:'Precio objetivo en EUR'});expect(input).toHaveAttribute('inputmode','decimal');expect(input).toHaveAttribute('placeholder','Precio objetivo €');
  fireEvent.change(input,{target:{value:'12,5'}});fireEvent.click(screen.getByRole('button',{name:'+ Alerta'}));
  await waitFor(()=>expect(m.success).toHaveBeenCalledOnce());expect(m.create).toHaveBeenCalledWith({symbol:'TEST',type:'price_below',condition:{operator:'<',value:12.5}});expect(input).toHaveValue('');
  expect(screen.getByRole('link',{name:'Ver alertas'})).toHaveAttribute('href','/alerts');
 });
 it('validates percentage type and formats percentage success without currency',async()=>{
  m.create.mockResolvedValue({ok:true});render(<QuickAlertButton ticker="TEST"/>);await open();await type('Cambio de precio %');fireEvent.click(screen.getByRole('button',{name:'+ Alerta'}));expect(m.error).toHaveBeenCalledWith('Introduce una variación objetivo válida');
  fireEvent.change(screen.getByRole('textbox',{name:'Variación objetivo en porcentaje'}),{target:{value:'5'}});fireEvent.click(screen.getByRole('button',{name:'+ Alerta'}));await waitFor(()=>expect(m.success).toHaveBeenCalledWith('Alerta creada: TEST cambio de precio % 5%'));
 });
 it.each(['Nueva noticia','Informe de ganancias'])('nonprice alert %s has no value field',async label=>{
  m.create.mockResolvedValue({ok:true});render(<QuickAlertButton ticker="TEST"/>);await open();await type(label);expect(screen.queryByRole('textbox')).not.toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'+ Alerta'}));await waitFor(()=>expect(m.success).toHaveBeenCalledWith(`Alerta creada: TEST · ${label}`));expect(m.create.mock.calls[0][0].condition.value).toBe('');
 });
 it.each(['duplicate','invalid_symbol'])('business rejection %s retains input without retry suggestion',async cause=>{
  m.create.mockResolvedValue({ok:false,cause,message:'Rechazo explícito'});render(<QuickAlertButton ticker="TEST" currency="ZZZ"/>);await open();const input=screen.getByRole('textbox');expect(input).toHaveAttribute('placeholder','Precio objetivo ZZZ ');fireEvent.change(input,{target:{value:'10'}});fireEvent.click(screen.getByRole('button',{name:'+ Alerta'}));await waitFor(()=>expect(cause==='duplicate'?m.info:m.error).toHaveBeenCalledWith('Rechazo explícito'));expect(input).toHaveValue('10');expect(m.showError).not.toHaveBeenCalled();expect(m.success).not.toHaveBeenCalled();
 });
 it('blocks submit while pending and exposes thrown failure retry',async()=>{
  let reject!:(e:Error)=>void;m.create.mockReturnValueOnce(new Promise((_,r)=>reject=r)).mockResolvedValueOnce({ok:true});render(<QuickAlertButton ticker="TEST"/>);await open();fireEvent.change(screen.getByRole('textbox'),{target:{value:'10'}});fireEvent.click(screen.getByRole('button',{name:'+ Alerta'}));expect(screen.getByRole('button',{name:'+ Alerta'})).toBeDisabled();
  const error=Error('Offline');await act(async()=>reject(error));expect(m.showError).toHaveBeenCalledWith(error,{duplicateMessage:'Ya tienes esta alerta configurada.',onRetry:expect.any(Function)});expect(screen.getByRole('button',{name:'+ Alerta'})).toBeEnabled();await act(async()=>m.showError.mock.calls[0][1].onRetry());expect(m.success).toHaveBeenCalledOnce();
 });
});
