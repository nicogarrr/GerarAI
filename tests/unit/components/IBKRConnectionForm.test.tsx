import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
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
