import {expect,it,vi} from 'vitest';
const request=vi.hoisted(()=>vi.fn());
vi.mock('@/lib/research/client',()=>({researchRequest:request}));
import {getDeepValue} from '@/lib/actions/propicks-deep-value.actions';
it('keeps old and new nullable-score payloads without inventing pending results',async()=>{
 const old={resultados:[]};request.mockResolvedValueOnce(old);expect(await getDeepValue()).toBe(old);
 expect(request).toHaveBeenLastCalledWith('/api/propicks/deep-value?pb_max=1&yield_min=0&limit=50',{fast:true});
 const current={resultados:[],pendientes_revision:[{score:null}]};request.mockResolvedValueOnce(current);expect(await getDeepValue(.5,.03)).toBe(current);
});
it('returns an honest error on network failure',async()=>{request.mockRejectedValueOnce(new Error('offline'));const log=vi.spyOn(console,'error').mockImplementation(()=>{});expect(await getDeepValue()).toHaveProperty('error');log.mockRestore();});
