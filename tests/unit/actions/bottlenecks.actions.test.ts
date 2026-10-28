import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest } = vi.hoisted(() => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest }));

import { getBottlenecks, getBottleneckDiscoveries, runBottleneckDiscovery } from '@/lib/actions/bottlenecks.actions';

beforeEach(() => { vi.clearAllMocks(); });

describe('cuellos de botella', () => {
    it('payload sin signals -> error explícito (no una lista vacía que parezca un dato)', async () => {
        researchRequest.mockResolvedValue({ signals: [{ theme: 'cobre' }], min_sources: 2 });
        expect(await getBottlenecks()).toMatchObject({ min_sources: 2 });
        researchRequest.mockResolvedValue({ signals: 'no-array' });
        await expect(getBottlenecks()).rejects.toThrow('no válida');
        researchRequest.mockResolvedValue(null);
        await expect(getBottlenecks()).rejects.toThrow('no válida');
    });

    it('discoveries: offset/limit saneados (offset negativo -> 0, limit 1..100)', async () => {
        researchRequest.mockResolvedValue({ items: [], total: 0 });
        await getBottleneckDiscoveries(-10, 999);
        expect(String(researchRequest.mock.calls[0][0])).toBe('/api/bottlenecks/discoveries?limit=100&offset=0');
        await getBottleneckDiscoveries(5.7, 0);
        expect(String(researchRequest.mock.calls[1][0])).toContain('limit=1&offset=5');
    });

    it('payload sin items -> error explícito', async () => {
        researchRequest.mockResolvedValue({});
        await expect(getBottleneckDiscoveries(0)).rejects.toThrow('no válida');
    });

    it('run encola el barrido sin prometer candidatos', async () => {
        researchRequest.mockResolvedValue({});
        const result = await runBottleneckDiscovery();
        expect(researchRequest).toHaveBeenCalledWith('/api/bottlenecks/discoveries/run', { method: 'POST' });
        expect(result.message).toContain('No garantiza candidatos');
    });
});
