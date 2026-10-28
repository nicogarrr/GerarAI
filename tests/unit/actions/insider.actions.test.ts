import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, cachedKeys } = vi.hoisted(() => ({
    researchRequest: vi.fn<(...args: any[]) => any>(async () => ({ status: 'ok' })),
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(async () => ({ id: 'user-1' })),
    cachedKeys: [] as string[],
}));
vi.mock('@/lib/research/client', () => ({ researchRequest }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/cache/memoryTTL', () => ({
    cachedFetch: (key: string, fetcher: () => Promise<unknown>) => { cachedKeys.push(key); return fetcher(); },
}));

import {
    getInsiderSignals, getInsiderFilings, loadMoreInsiderFilings,
    getInsiderFeed, getInsiderOperations, getOwnershipSignals,
} from '@/lib/actions/insider.actions';

beforeEach(() => {
    vi.clearAllMocks();
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
    researchRequest.mockResolvedValue({ status: 'ok' });
    cachedKeys.length = 0;
});

describe('clave de caché con identidad (nunca datos de otro usuario)', () => {
    it('signals, filings, feed, operations y ownership van prefijados por userId', async () => {
        await getInsiderSignals('aapl');
        await getInsiderFilings('AAPL');
        await getInsiderFeed('compra', 30);
        await getInsiderOperations(365);
        await getOwnershipSignals('AAPL');
        for (const key of cachedKeys) expect(key.startsWith('insider:user:user-1:')).toBe(true);
    });

    it('el auth va ANTES de cualquier llamada al backend', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('no auth'));
        await expect(getInsiderSignals('AAPL')).rejects.toThrow('no auth');
        expect(researchRequest).not.toHaveBeenCalled();
    });
});

describe('normalización y parámetros', () => {
    it('ticker limpio en mayúsculas en path y clave', async () => {
        await getInsiderSignals('  aapl ', { limit: 5 });
        expect(String(researchRequest.mock.calls[0][0])).toContain('ticker=AAPL');
        expect(String(researchRequest.mock.calls[0][0])).toContain('limit=5');
        expect(cachedKeys[0]).toContain(':AAPL:5');
    });

    it('notify=true va DIRECTO al backend (una notificación no se cachea)', async () => {
        await getInsiderSignals('AAPL', { notify: true });
        expect(cachedKeys).toHaveLength(0);
        expect(String(researchRequest.mock.calls[0][0])).toContain('notify=true');
    });

    it('loadMoreInsiderFilings acota offset>=0 y limit 1..50, sin caché', async () => {
        await loadMoreInsiderFilings('AAPL', -5, 999);
        expect(String(researchRequest.mock.calls[0][0])).toContain('offset=0');
        expect(String(researchRequest.mock.calls[0][0])).toContain('limit=50');
        expect(cachedKeys).toHaveLength(0);
        await loadMoreInsiderFilings('AAPL', Number.NaN, 0);
        expect(String(researchRequest.mock.calls[1][0])).toContain('offset=0');
        expect(String(researchRequest.mock.calls[1][0])).toContain('limit=20'); // 0/NaN -> default
    });
});
