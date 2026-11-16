import {beforeEach, expect, it, vi} from 'vitest';
const {request,user}=vi.hoisted(()=>({request:vi.fn(),user:vi.fn()}));
vi.mock('@/lib/research/client',()=>({researchRequest:request,jsonBody:JSON.stringify}));
vi.mock('@/lib/auth/require-user',()=>({requireAuthenticatedUser:user}));
vi.mock('@/lib/research/backend-error-locale',()=>({requestLocale:async()=>'es'}));
import {chatWithPortfolio} from '@/lib/actions/brain.actions';
import {AppError,ExternalAPIError} from '@/lib/types/errors';
beforeEach(()=>{request.mockReset().mockResolvedValue({answer:'ok',blocked:false,proposed_actions:[],sources:[]});user.mockReset().mockResolvedValue({id:'u1'});});
it('omits model by default and forwards only explicitly allowed selection',async()=>{
 await chatWithPortfolio('Consulta','u1');expect(JSON.parse(request.mock.calls[0][1].body)).not.toHaveProperty('model');
 await chatWithPortfolio('Consulta','u1',null,[], 'hy4-flash-free');expect(JSON.parse(request.mock.calls[1][1].body).model).toBe('hy4-flash-free');
 expect(request.mock.calls[1][0]).toBe('/api/chat');
});
it('rejects forged models, short questions and other users before a backend request',async()=>{
 await expect(chatWithPortfolio('Consulta','other')).rejects.toThrow();
 await expect(chatWithPortfolio('  ','u1')).rejects.toThrow();
 await expect(chatWithPortfolio('Consulta','u1',null,[], 'other' as 'hy4-flash-free')).rejects.toThrow();
 expect(request).not.toHaveBeenCalled();
});
it('keeps context, histories and blocked replies',async()=>{
 const page={path:'/portfolio',label:'Cartera',ticker:null};
 request.mockResolvedValue({answer:'bloqueado',blocked:true,proposed_actions:[],sources:[],context:{...page,company_name:null,company_resolved:false}});
 const result=await chatWithPortfolio('Consulta','u1',page,[{role:'user',content:'previa'}]);expect(result.success).toBe(false);expect(result.context?.path).toBe('/portfolio');
 expect(JSON.parse(request.mock.calls[0][1].body).history).toEqual([{role:'user',content:'previa'}]);
});
it('maps known transport failures but does not hide auth or validation errors',async()=>{
 for(const code of [429,504,502,503]){request.mockRejectedValueOnce(new AppError('private detail','RESEARCH_API_ERROR',code));const result=await chatWithPortfolio('Consulta','u1');expect(result.success).toBe(false);expect(result.message).not.toContain('private detail');}
 request.mockRejectedValueOnce(new ExternalAPIError('timeout','research',new DOMException('slow','TimeoutError')));expect((await chatWithPortfolio('Consulta','u1')).message).toContain('tarda');
 request.mockRejectedValueOnce(new ExternalAPIError('offline','research',new Error('offline')));expect((await chatWithPortfolio('Consulta','u1')).success).toBe(false);
 request.mockRejectedValueOnce(new Error('unexpected'));await expect(chatWithPortfolio('Consulta','u1')).rejects.toThrow('unexpected');
 request.mockRejectedValueOnce(new AppError('denied','RESEARCH_API_ERROR',401));await expect(chatWithPortfolio('Consulta','u1')).rejects.toThrow('denied');
});
