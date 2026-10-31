import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
const mocks=vi.hoisted(()=>({save:vi.fn(),success:vi.fn(),error:vi.fn()}));
vi.mock('@/lib/actions/portfolio-settings.actions',()=>({savePortfolioBaseCurrency:mocks.save}));
vi.mock('sonner',()=>({toast:{success:mocks.success}}));
vi.mock('@/lib/toast',()=>({showErrorToast:mocks.error}));
import BaseCurrencyForm from '@/components/settings/BaseCurrencyForm';
async function selectUsd(){fireEvent.keyDown(screen.getByRole('combobox',{name:'Divisa base'}),{key:'ArrowDown'});fireEvent.click(await screen.findByRole('option',{name:'USD · Dólar estadounidense'}));}
beforeEach(()=>vi.clearAllMocks());
describe('base currency save control',()=>{
 it('blocks saving unchanged currency and shows supplied source date',()=>{
  render(<BaseCurrencyForm initial={{id:1,name:'Main',base_currency:'eur',is_default:true,tax_currency:'EUR',fx_source:{source:'BCE',latest_rate_date:'2026-10-27',base_currency:'EUR'}}}/>);
  expect(screen.getByRole('button',{name:'Guardar'})).toBeDisabled();expect(screen.getByText(/Tipos de cambio: BCE, último del/)).toBeVisible();
 });
 it('shows default currency and honest missing FX date',()=>{
  render(<BaseCurrencyForm initial={{id:null,name:'Main',base_currency:'',is_default:true,tax_currency:'EUR',fx_source:{source:null,latest_rate_date:null,base_currency:'EUR'}}}/>);
  expect(screen.getByRole('combobox')).toHaveTextContent('EUR');expect(screen.getByText(/sin tipos descargados todavía/)).toBeVisible();
 });
 it('retains a saved currency outside the menu catalog',async()=>{
  render(<BaseCurrencyForm initial={{id:1,name:'Main',base_currency:'AUD',is_default:true,tax_currency:'EUR',fx_source:{source:'BCE',latest_rate_date:'2026-10-27',base_currency:'AUD'}}}/>);expect(screen.getByRole('combobox')).toHaveTextContent('AUD');
  fireEvent.keyDown(screen.getByRole('combobox'),{key:'ArrowDown'});expect(await screen.findByRole('option',{name:'AUD'})).toBeVisible();
 });
 it('sends selected currency, blocks save while pending and marks confirmed value saved',async()=>{
  let resolve!:(v:unknown)=>void;mocks.save.mockReturnValue(new Promise(r=>resolve=r));
  render(<BaseCurrencyForm initial={{id:1,name:'Main',base_currency:'EUR',is_default:true,tax_currency:'EUR',fx_source:{source:'BCE',latest_rate_date:'2026-10-27',base_currency:'EUR'}}}/>);await selectUsd();
  fireEvent.click(screen.getByRole('button',{name:'Guardar'}));expect(mocks.save).toHaveBeenCalledWith('USD');
  expect(screen.getByRole('button',{name:'Guardando…'})).toBeDisabled();
  await act(async()=>resolve({id:1,name:'Main',base_currency:'USD',is_default:true}));
  expect(mocks.success).toHaveBeenCalledWith('Divisa base: USD. Cartera revalorada.');
  expect(screen.getByRole('button',{name:'Guardar'})).toBeDisabled();expect(mocks.error).not.toHaveBeenCalled();
 });
 it('failed save retains unsaved selection, exposes error and permits retry',async()=>{
  const error=Error('Sin conexión');mocks.save.mockRejectedValueOnce(error).mockResolvedValueOnce({id:1,name:'Main',base_currency:'USD',is_default:true});
  render(<BaseCurrencyForm initial={{id:1,name:'Main',base_currency:'EUR',is_default:true,tax_currency:'EUR',fx_source:{source:'BCE',latest_rate_date:'2026-10-27',base_currency:'EUR'}}}/>);await selectUsd();fireEvent.click(screen.getByRole('button',{name:'Guardar'}));
  await waitFor(()=>expect(mocks.error).toHaveBeenCalledWith(error));
  expect(screen.getByRole('combobox')).toHaveTextContent('USD');expect(screen.getByRole('button',{name:'Guardar'})).toBeEnabled();expect(mocks.success).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Guardar'}));await waitFor(()=>expect(mocks.success).toHaveBeenCalledOnce());
  expect(mocks.save).toHaveBeenCalledTimes(2);expect(screen.getByRole('button',{name:'Guardar'})).toBeDisabled();
 });
});
