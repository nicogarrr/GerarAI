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
