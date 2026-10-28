import { beforeEach, describe, expect, it, vi } from 'vitest';
const auth = vi.fn();
const request = vi.fn();
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: () => auth() }));
vi.mock('@/lib/research/client', () => ({ researchRequest: (...args: unknown[]) => request(...args) }));
import { getHomeAttention } from '@/lib/actions/home-attention.actions';
beforeEach(() => { auth.mockReset().mockResolvedValue({id:'user'}); request.mockReset(); });
describe('home attention read action', () => {
    it('authenticates before either source', async () => {
        auth.mockRejectedValue(new Error('no session'));
        await expect(getHomeAttention()).rejects.toThrow('no session');
        expect(request).not.toHaveBeenCalled();
    });
    it('keeps partial failure separate', async () => {
        request.mockImplementation((url: string) => url.endsWith('attention-thesis') ? Promise.reject(new Error('offline')) : Promise.resolve({items:[]}));
        expect(await getHomeAttention()).toEqual({thesis:{unavailable:true,items:[]},dca:{unavailable:false,items:[]}});
        expect(request).toHaveBeenCalledTimes(2);
    });
    it('does not silently call malformed response an empty source', async () => {
        request.mockResolvedValue({});
        expect(await getHomeAttention()).toEqual({thesis:{unavailable:true,items:[]},dca:{unavailable:true,items:[]}});
    });
    it('preserves truncation and actual thesis changes', async () => {
        request.mockImplementation((url:string) => Promise.resolve(url.endsWith('attention-thesis') ? {items:[{id:1}],truncated:true} : {items:[]}));
        expect((await getHomeAttention()).thesis).toMatchObject({unavailable:false,truncated:true,items:[{id:1}]});
    });
});
