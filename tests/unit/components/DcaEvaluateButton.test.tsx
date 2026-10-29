import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
const action=vi.fn(),poll=vi.fn(),refresh=vi.fn(),success=vi.fn(),warning=vi.fn();
afterEach(()=>{vi.useRealTimers();vi.clearAllMocks();});
vi.mock('next/navigation',()=>({useRouter:()=>({refresh})}));
vi.mock('@/lib/actions/dca-signals.actions',()=>({startDcaManualJob:()=>action(),getDcaManualJob:()=>poll()}));
vi.mock('sonner',()=>({toast:{success:(x:string)=>success(x),warning:(x:string)=>warning(x)}}));
import DcaEvaluateButton from '@/components/watchlist/DcaEvaluateButton';
it('solo pide una tanda, bloquea durante ejecución y muestra pendientes',async()=>{
 vi.useFakeTimers({shouldAdvanceTime:true});
 poll.mockResolvedValue({success:true,status:'ok',summary:{evaluated:10,alerted:[],skipped:[],pending_remaining:13}});
 let resolve!: (v:unknown)=>void;action.mockReturnValue(new Promise(r=>{resolve=r}));render(<DcaEvaluateButton/>);
 const button=screen.getByRole('button',{name:'Ejecutar pendientes ahora'});fireEvent.click(button);
 expect(button).toBeDisabled();
 resolve({success:true,runId:123});
 await vi.advanceTimersByTimeAsync(5100);
 await waitFor(()=>expect(refresh).toHaveBeenCalledTimes(1));
 expect(action).toHaveBeenCalledTimes(1);expect(success).toHaveBeenCalledWith(expect.stringContaining('13 pendientes'));
 expect(screen.getByRole('link')).toHaveAttribute('href','/plan');
});

it('no anuncia éxito completo cuando hay errores por empresa',async()=>{
 vi.useFakeTimers({shouldAdvanceTime:true});
 action.mockResolvedValue({success:true,runId:124});
 poll.mockResolvedValue({success:true,status:'ok',summary:{evaluated:0,alerted:[],skipped:[],errors:[{symbol:'AAPL',error:'TimeoutError'}],pending_remaining:0}});
 render(<DcaEvaluateButton/>);fireEvent.click(screen.getByRole('button',{name:'Ejecutar pendientes ahora'}));
 await vi.advanceTimersByTimeAsync(5100);
 await waitFor(()=>expect(refresh).toHaveBeenCalledTimes(1));
 expect(success).not.toHaveBeenCalled();
 expect(warning).toHaveBeenCalledWith(expect.stringContaining('1 empresa con errores'));
});
