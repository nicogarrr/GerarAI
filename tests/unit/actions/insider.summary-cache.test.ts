import {beforeEach,expect,it,vi} from 'vitest';
import {requestCache} from '@/lib/cache/requestCache';
const {researchRequest}=vi.hoisted(()=>({researchRequest:vi.fn()}));
vi.mock('@/lib/research/client',()=>({researchRequest}));
vi.mock('@/lib/auth/require-user',()=>({requireAuthenticatedUser:async()=>({id:'user-1'})}));
import {getInsiderSummary} from '@/lib/actions/insider.actions';
beforeEach(()=>{requestCache.clear();vi.clearAllMocks();});
it('bypasses legacy summary cache with PDMR monetary windows and clusters',async()=>{
 const legacy={ticker:'MNTN.L',status:'ok',windows:[{days:90,buys:{value:99999},net_value:99999}],clusters:[{value:99999}],transactions:[{form:'PDMR',value:99999}]};
 const fresh={...legacy,windows:[{days:90,buys:{value:null},net_value:null}],clusters:[{value:null}]};
 await requestCache.get('insider:user:user-1:summary:MNTN.L',async()=>legacy,60);
 researchRequest.mockResolvedValue(fresh);
 expect(await getInsiderSummary(' mntn.l ')).toEqual(fresh);
 expect(researchRequest).toHaveBeenCalledTimes(1);
 expect(await getInsiderSummary('MNTN.L')).toEqual(fresh);
 expect(researchRequest).toHaveBeenCalledTimes(1);
});
