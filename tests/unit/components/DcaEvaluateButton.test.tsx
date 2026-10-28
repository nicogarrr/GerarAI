import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
const action=vi.fn(),refresh=vi.fn(),success=vi.fn();
vi.mock('next/navigation',()=>({useRouter:()=>({refresh})}));
vi.mock('@/lib/actions/dca-signals.actions',()=>({evaluateDcaSignalsNow:()=>action()}));
vi.mock('sonner',()=>({toast:{success:(x:string)=>success(x)}}));
import DcaEvaluateButton from '@/components/watchlist/DcaEvaluateButton';
it('solo pide una tanda, bloquea durante ejecución y muestra pendientes',async()=>{
 let resolve!: (v:unknown)=>void;action.mockReturnValue(new Promise(r=>{resolve=r}));render(<DcaEvaluateButton/>);
 const button=screen.getByRole('button',{name:'Ejecutar pendientes ahora'});fireEvent.click(button);
 expect(button).toBeDisabled();
 resolve({success:true,summary:{evaluated:10,alerted:[],skipped:[],pending_remaining:13}});
 await waitFor(()=>expect(refresh).toHaveBeenCalledTimes(1));
 expect(action).toHaveBeenCalledTimes(1);expect(success).toHaveBeenCalledWith(expect.stringContaining('13 pendientes'));
 expect(screen.getByRole('link')).toHaveAttribute('href','/plan');
});
