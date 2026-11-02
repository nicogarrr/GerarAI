import { LocaleProvider } from '@/lib/i18n/client';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import IBKRConnectionForm from '@/components/settings/IBKRConnectionForm';
import type { IBKRConnection } from '@/lib/actions/ibkr-settings.actions';
const connect = vi.fn(); const sync = vi.fn(); const disconnect = vi.fn();
vi.mock('@/lib/actions/ibkr-settings.actions', () => ({
 connectIBKR:(...args:unknown[])=>connect(...args),syncIBKR:()=>sync(),disconnectIBKR:()=>disconnect(),
}));
const empty: IBKRConnection={connected:false,account_id:null,query_id:null,status:'not_connected',message:'Sin conectar',complete_query:false,last_attempt_at:null,last_success_at:null,statement_date:null};
const active: IBKRConnection={...empty,connected:true,account_id:'U1234567',query_id:'12345',status:'connected'};
beforeEach(()=>{connect.mockReset();sync.mockReset();disconnect.mockReset();});
it('does not fabricate a connection and hides token input after successful verified connect',async()=>{
 connect.mockResolvedValue({ok:true,connection:active});sync.mockResolvedValue({ok:true,connection:{...active,message:'Sincronizado'}});
 render(<IBKRConnectionForm initial={empty}/>);
 expect(screen.getByRole('button',{name:'Conectar e importar'})).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Token Flex'),{target:{value:'1234567890'}});
 fireEvent.change(screen.getByLabelText('Query ID'),{target:{value:'12345'}});
 fireEvent.change(screen.getByLabelText('Cuenta IBKR'),{target:{value:'U1234567'}});
 fireEvent.submit(screen.getByRole('form',{name:'Conectar IBKR'}));
 await waitFor(()=>expect(sync).toHaveBeenCalledOnce());
 expect(connect).toHaveBeenCalledWith({token:'1234567890',query_id:'12345',account_id:'U1234567',complete_query:false});
 expect(screen.queryByLabelText('Token Flex')).not.toBeInTheDocument();
});
it('failed verification never imports and clears token',async()=>{
 connect.mockResolvedValue({ok:false,message:'Cuenta incorrecta'});
 render(<IBKRConnectionForm initial={empty}/>);
 fireEvent.change(screen.getByLabelText('Token Flex'),{target:{value:'1234567890'}});
 fireEvent.submit(screen.getByRole('form',{name:'Conectar IBKR'}));
 await waitFor(()=>expect(screen.getByRole('status')).toHaveTextContent('Cuenta incorrecta'));
 expect(sync).not.toHaveBeenCalled();expect(screen.getByLabelText('Token Flex')).toHaveValue('');
});
it('disconnect requires confirmation and retains account binding afterwards',async()=>{
 disconnect.mockResolvedValue({ok:true,connection:{...active,connected:false,status:'disconnected'}});
 render(<IBKRConnectionForm initial={active}/>);
 fireEvent.click(screen.getByRole('button',{name:'Desconectar'}));expect(disconnect).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Confirmar desconexión'}));
 await waitFor(()=>expect(screen.getByLabelText('Cuenta IBKR')).toBeDisabled());
 expect(screen.getByLabelText('Cuenta IBKR')).toHaveValue('U1234567');
});

it('explains browser-only setup, report freshness and delayed data without inventing Spanish menu labels', () => {
 render(<IBKRConnectionForm initial={empty}/>);
 expect(screen.getByText('Debe hacerse desde la web de IBKR (Portal del Cliente), no desde la app móvil.')).toBeInTheDocument();
 const guide = screen.getByText('Cómo conseguir token y Query ID').parentElement!;
 expect(guide.textContent).toContain('máximo 5 días');
 expect(guide.textContent).toContain('no datos en tiempo real');
 expect(guide.textContent).toContain('No hemos comprobado los nombres exactos');
 expect(guide.textContent).toContain('Cash Transactions');
 expect(guide.textContent).toContain('Corporate Actions');
 expect(guide.textContent).toContain('Generar uno nuevo invalida el anterior');
 expect(guide.textContent).toContain('no el número de cuenta');
 expect(screen.getByRole('link', { name: 'Guía oficial: consulta y Query ID' })).toHaveAttribute('href','https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/create-a-flex-query.md');
});

describe('in English', () => {
 const renderEn = (initial: IBKRConnection) => render(<LocaleProvider locale="en"><IBKRConnectionForm initial={initial}/></LocaleProvider>);
 it('shows the stored IBKR status message in English (stored data stays Spanish)', () => {
  renderEn({...active,message:'Posiciones y caja sincronizadas con el extracto de IBKR.'});
  expect(screen.getByRole('status')).toHaveTextContent('Positions and cash synced with the IBKR statement.');
 });
 it.each([
  ['Conexión verificada. Pulsa Sincronizar para importar posiciones y caja.', 'Connection verified. Press Sync to import positions and cash.'],
  ['Desconectado. Se han conservado las posiciones y operaciones importadas.', 'Disconnected. The imported positions and trades have been kept.'],
  ['Datos actualizados sin cerrar posiciones ausentes. Confirma una consulta completa para reconciliar la cartera.', 'Data updated without closing missing positions. Confirm a complete query to reconcile the portfolio.'],
  ['Importación parcial: revisa la consulta antes de dar la cartera por completa.', 'Partial import: check the query before treating the portfolio as complete.'],
  ['No se pudo sincronizar. Conservamos los datos anteriores; revisa la conexión y vuelve a intentarlo.', 'Sync failed. We kept the previous data; check the connection and try again.'],
 ])('stored «%s» reads in English', (stored, english) => {
  renderEn({...active,status:'error',message:stored});
  expect(screen.getByRole('status')).toHaveTextContent(english);
 });
 it('a failed sync shows the English fallback', async () => {
  sync.mockResolvedValue({ok:false,message:'No se pudo sincronizar. Conservamos los datos anteriores. Revisa la consulta o vuelve a intentarlo cuando IBKR termine el informe.'});
  renderEn(active);
  fireEvent.click(screen.getByRole('button',{name:'Sync now'}));
  await waitFor(()=>expect(screen.getByRole('status')).toHaveTextContent('Sync failed. We kept the previous data. Check the query or try again when IBKR finishes the report.'));
 });
 it('a failed verification and a failed disconnect show English fallbacks', async () => {
  connect.mockResolvedValue({ok:false,message:'No se pudo verificar la conexión. Revisa token, Query ID y cuenta. La consulta debe incluir posiciones y caja del mismo cierre, en XML; IBKR puede tardar en prepararla.'});
  renderEn(empty);
  fireEvent.change(screen.getByLabelText('Flex token'),{target:{value:'1234567890'}});
  fireEvent.submit(screen.getByRole('form'));
  await waitFor(()=>expect(screen.getByRole('status')).toHaveTextContent('Could not verify the connection. Check the token, Query ID and account. The query must include positions and cash from the same close, in XML; IBKR may take a while to prepare it.'));
 });
 it('Spanish keeps the stored message as is', () => {
  render(<IBKRConnectionForm initial={{...active,message:'Posiciones y caja sincronizadas con el extracto de IBKR.'}}/>);
  expect(screen.getByRole('status')).toHaveTextContent('Posiciones y caja sincronizadas con el extracto de IBKR.');
 });
});
