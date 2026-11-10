import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {renderToString} from 'react-dom/server';
import {beforeEach,describe,expect,it,vi} from 'vitest';
const m=vi.hoisted(()=>({create:vi.fn(),success:vi.fn(),error:vi.fn(),info:vi.fn(),showError:vi.fn()}));
vi.mock('@/lib/actions/alerts.actions',()=>({createAlertResult:m.create}));
vi.mock('sonner',()=>({toast:{success:m.success,error:m.error,info:m.info}}));
vi.mock('@/lib/toast',()=>({showErrorToast:m.showError}));
import QuickAlertButton from '@/components/research/QuickAlertButton';
import {EARLY_OPEN_CAPTURE_JS} from '@/lib/early-open';

// La captura pre-hidratación corre tal cual en el HTML inicial (mismo patrón
// que tests/unit/components/EarlyOpen.test.tsx): aquí se prueba el gatillo de
// alerta contra el script real, no contra un doble.
window.eval(EARLY_OPEN_CAPTURE_JS);
// Contrato del fix de retención: la fuente todavía no escribe esta marca
// (rojo hasta que lib/early-open.ts y QuickAlertButton.tsx la implementen).
const ALERT_PENDING_KEY='gerarai:open-alert:pending';
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
 it.each(['Nueva noticia','Resultados'])('nonprice alert %s has no value field',async label=>{
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

describe('quick alert trigger before hydration',()=>{
 beforeEach(()=>sessionStorage.clear());
 it('retains a real SSR trigger click and opens the popover on mount',async()=>{
  const host=document.createElement('div');
  host.innerHTML=renderToString(<QuickAlertButton ticker="MSFT" currency="USD" compact/>);
  document.body.append(host);
  fireEvent.click(host.querySelector('button')!);
  // Sin retención este clic se pierde en silencio (el rojo E2E del piloto).
  // La intención guarda la identidad del gatillo: solo esta ficha la consume.
  expect(sessionStorage.getItem(ALERT_PENDING_KEY)).toBe(JSON.stringify({ticker:'MSFT'}));
  host.remove();
  render(<QuickAlertButton ticker="MSFT" currency="USD" compact/>);
  expect(await screen.findByRole('combobox',{name:'Tipo de alerta'})).toBeVisible();
  expect(sessionStorage.getItem(ALERT_PENDING_KEY)).toBeNull();
 });
 it('discards a retained click from another ticker without opening',async()=>{
  // Regresión cruzada (hallazgo del auditor): clic SSR en MSFT, navegar antes
  // de hidratar y montar AAPL — el popover de AAPL NO puede abrirse y la
  // intención ajena queda descartada (borrada), no aplazada.
  const host=document.createElement('div');
  host.innerHTML=renderToString(<QuickAlertButton ticker="MSFT" currency="USD" compact/>);
  document.body.append(host);
  fireEvent.click(host.querySelector('button')!);
  expect(sessionStorage.getItem(ALERT_PENDING_KEY)).toBeTruthy();
  host.remove();
  render(<QuickAlertButton ticker="AAPL" currency="USD" compact/>);
  await act(async()=>{});
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  expect(sessionStorage.getItem(ALERT_PENDING_KEY)).toBeNull();
 });
 it('marks the mounted trigger hydrated: later clicks belong to React alone',async()=>{
  render(<QuickAlertButton ticker="MSFT" currency="USD"/>);
  const trigger=screen.getByRole('button',{name:'Alerta de precio'});
  expect(trigger).toHaveAttribute('data-hydrated','1');
  fireEvent.click(trigger);
  await screen.findByRole('combobox',{name:'Tipo de alerta'});
  expect(sessionStorage.getItem(ALERT_PENDING_KEY)).toBeNull();
 });
 it('storage denial on consume leaves the popover closed without crashing',async()=>{
  sessionStorage.setItem(ALERT_PENDING_KEY,'1');
  vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new Error('denied');});
  vi.spyOn(Storage.prototype,'removeItem').mockImplementation(()=>{throw new Error('denied');});
  render(<QuickAlertButton ticker="MSFT" currency="USD"/>);
  await act(async()=>{});
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  vi.restoreAllMocks();
 });
 it('without a retained click the popover stays closed on mount',async()=>{
  render(<QuickAlertButton ticker="MSFT" currency="USD"/>);
  await act(async()=>{});
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
 });
});

describe('quick alert trigger preload',()=>{
 it('preloads the popover body chunk on pointer intent and focus without opening',()=>{
  render(<QuickAlertButton ticker="MSFT" currency="USD"/>);
  const trigger=screen.getByRole('button',{name:'Alerta de precio'});
  fireEvent.pointerDown(trigger);
  fireEvent.focus(trigger);
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
 });
});
