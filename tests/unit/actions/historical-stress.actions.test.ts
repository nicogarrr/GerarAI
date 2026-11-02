import { beforeEach, expect, it, vi } from 'vitest';
const request = vi.hoisted(() => vi.fn());
vi.mock('@/lib/research/client', () => ({ researchRequest: request }));
import { getHistoricalStress } from '@/lib/actions/historical-stress.actions';
beforeEach(() => request.mockReset());
it('uses the shared bounded request and URL encodes ticker', async () => {
    const report = { scenarios: [] };
    request.mockResolvedValue(report);
    expect(await getHistoricalStress('A&B')).toBe(report);
    expect(request).toHaveBeenCalledExactlyOnceWith('/api/risk/historical-stress?ticker=A%26B');
});
it('keeps backend failures visible instead of fabricating a report', async () => {
    const error = new Error('offline');
    request.mockRejectedValue(error);
    await expect(getHistoricalStress()).rejects.toBe(error);
});
