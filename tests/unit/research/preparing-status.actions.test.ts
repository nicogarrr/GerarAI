import {beforeEach, expect, it, vi} from 'vitest';
const request = vi.fn(); const auth = vi.fn();
vi.mock('@/lib/research/client', () => ({researchRequest: (...a: unknown[]) => request(...a)}));
vi.mock('@/lib/auth/require-user', () => ({requireAuthenticatedUser: () => auth()}));
import {getPreparingStatus} from '@/lib/actions/preparing-status.actions';
beforeEach(() => {request.mockReset(); auth.mockReset();});
it('validates inputs before access and does not trust client kind', async () => {
 expect(await getPreparingStatus('bad/slash','news')).toBe('unavailable');
 expect(await getPreparingStatus('ASTS','other' as 'news')).toBe('unavailable');
 expect(auth).not.toHaveBeenCalled();
});
it('polls authenticated narrow state only', async () => {
 request.mockResolvedValueOnce({preparing:true}).mockResolvedValueOnce({preparing:false}).mockResolvedValueOnce({available:true,rows:[]});
 expect(await getPreparingStatus('ASTS','dca')).toBe('preparing');
 expect(await getPreparingStatus('BRK.B','news')).toBe('ready');
 expect(await getPreparingStatus('ASTS','dca')).toBe('ready');
 expect(request.mock.calls.map(a=>a[0])).toEqual(['/api/watchlist/dca-signals/ASTS/hit-rates','/api/watchlist/news-preparing/BRK.B','/api/watchlist/dca-signals/ASTS/hit-rates']);
 expect(auth).toHaveBeenCalledTimes(3);
});
it('errors, malformed data and missing session never report completion', async () => {
 for (const data of [null,{}, {preparing:'false'}]) {request.mockResolvedValue(data); expect(await getPreparingStatus('ASTS','news')).toBe('unavailable');expect(await getPreparingStatus('ASTS','dca')).toBe('unavailable');}
 request.mockRejectedValue(new Error('offline'));expect(await getPreparingStatus('ASTS','news')).toBe('unavailable');
 auth.mockRejectedValue(new Error('signed out'));expect(await getPreparingStatus('ASTS','dca')).toBe('unavailable');
});
