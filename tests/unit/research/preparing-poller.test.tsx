import {act, cleanup, render} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
const read=vi.fn(); const refresh=vi.fn();
vi.mock('@/lib/actions/preparing-status.actions',()=>({getPreparingStatus:(...a:unknown[])=>read(...a)}));
vi.mock('next/navigation',()=>({useRouter:()=>({refresh})}));
import DcaPreparingRefresh from '@/components/research/DcaPreparingRefresh';
import {watchPreparing} from '@/lib/research/preparing-poller';
beforeEach(()=>{vi.useFakeTimers();read.mockReset().mockResolvedValue('preparing');refresh.mockReset();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');});
afterEach(()=>{cleanup();vi.useRealTimers();vi.restoreAllMocks();});
const tick=async(n=30_000)=>{await act(async()=>{await vi.advanceTimersByTimeAsync(n);});};
it('coalesces card copies, polls status and refreshes just once on completion',async()=>{
 read.mockResolvedValueOnce('preparing').mockResolvedValue('ready');
 render(<><DcaPreparingRefresh ticker="READY" kind="dca"/><DcaPreparingRefresh ticker="READY" kind="dca"/></>);
 await tick();expect(read).toHaveBeenCalledTimes(1);expect(refresh).not.toHaveBeenCalled();
 await tick();expect(refresh).toHaveBeenCalledTimes(1);await tick(90_000);expect(read).toHaveBeenCalledTimes(2);
});
it('retains attempt budget across unmount and remount',async()=>{
 const first=render(<DcaPreparingRefresh ticker="BUDGET" kind="news"/>);await tick(30_000*10);first.unmount();
 render(<DcaPreparingRefresh ticker="BUDGET" kind="news"/>);await tick(30_000*30);expect(read).toHaveBeenCalledTimes(20);expect(refresh).not.toHaveBeenCalled();
});
it('pauses hidden tabs and expires by wall time',async()=>{
 vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');
 render(<DcaPreparingRefresh ticker="HIDDEN" kind="dca"/>);await tick(30_000*21);expect(read).not.toHaveBeenCalled();
});
it('does not overlap slow calls or invoke unmounted listeners',async()=>{
 let resolve!:(v:'ready')=>void;read.mockImplementation(()=>new Promise(r=>{resolve=r;}));
 const view=render(<DcaPreparingRefresh ticker="SLOW" kind="news"/>);await tick();await tick(90_000);expect(read).toHaveBeenCalledTimes(1);
 view.unmount();await act(async()=>{resolve('ready');});expect(refresh).not.toHaveBeenCalled();
});
it('handles rejected reads without refreshing and stops after unsubscribe',async()=>{
 const reject=vi.fn().mockRejectedValue(new Error('offline'));const ready=vi.fn();
 const stop=watchPreparing('reject',reject,ready);await tick();expect(ready).not.toHaveBeenCalled();await tick(90_000);expect(reject).toHaveBeenCalledTimes(1);stop();
});
it('changing ticker cancels old subscription and reads the new ticker',async()=>{
 const view=render(<DcaPreparingRefresh ticker="OLD" kind="dca"/>);view.rerender(<DcaPreparingRefresh ticker="NEW" kind="dca"/>);await tick();expect(read).toHaveBeenCalledWith('NEW','dca');expect(read).toHaveBeenCalledTimes(1);
});
