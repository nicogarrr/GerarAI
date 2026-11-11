import { beforeEach, expect, it, vi } from 'vitest';
const m=vi.hoisted(()=>({auth:vi.fn(),request:vi.fn()}));
vi.mock('@/lib/auth/require-user',()=>({requireAuthenticatedUser:m.auth}));
vi.mock('@/lib/research/client',()=>({researchRequest:m.request}));
import {getAiAvailability} from '@/lib/actions/ai-availability.actions';
beforeEach(()=>vi.resetAllMocks());
it('authenticates before the read-only no-store feature check',async()=>{m.request.mockResolvedValue({can_start:false});expect(await getAiAvailability('thesis')).toEqual({can_start:false});expect(m.auth).toHaveBeenCalledOnce();expect(m.request).toHaveBeenCalledWith('/api/settings/llm/availability?feature=thesis',{cache:'no-store'});});
it('does not inspect readiness when authentication fails',async()=>{m.auth.mockRejectedValue(new Error('auth'));await expect(getAiAvailability('chat')).rejects.toThrow('auth');expect(m.request).not.toHaveBeenCalled();});
