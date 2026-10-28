import { describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ auth: vi.fn(), request: vi.fn(), revalidate: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: mocks.auth }));
vi.mock('@/lib/research/client', () => ({ researchRequest: mocks.request, jsonBody: JSON.stringify }));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidate }));
import { getDcaAlertSettings, saveDcaAlertSettings } from '@/lib/actions/dca-settings.actions';

describe('DCA settings actions', () => {
    it('reads fresh from authenticated tenant', async () => {
        mocks.auth.mockResolvedValue({ id: 'u' }); mocks.request.mockResolvedValue({ up_min_level: 3 });
        expect(await getDcaAlertSettings()).toEqual({ up_min_level: 3 });
        expect(mocks.request).toHaveBeenCalledWith('/api/settings/dca', { cache: 'no-store' });
    });
    it('saves directions and invalidates both surfaces', async () => {
        mocks.auth.mockResolvedValue({ id: 'u' }); mocks.request.mockResolvedValue({ configured: true });
        await saveDcaAlertSettings(3, 1);
        expect(mocks.request).toHaveBeenCalledWith('/api/settings/dca', { method: 'PUT', body: '{"up_min_level":3,"down_max_level":1}' });
        expect(mocks.revalidate).toHaveBeenCalledWith('/settings'); expect(mocks.revalidate).toHaveBeenCalledWith('/watchlist');
    });
    it('rejects invalid values and missing auth', async () => {
        mocks.auth.mockResolvedValue({ id: 'u' });
        await expect(saveDcaAlertSettings(5, 1)).rejects.toThrow('Nivel DCA no válido');
        mocks.auth.mockRejectedValueOnce(new Error('not authenticated'));
        await expect(saveDcaAlertSettings(3, 1)).rejects.toThrow('not authenticated');
    });
});
