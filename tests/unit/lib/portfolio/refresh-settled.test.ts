// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { partitionSettledRefreshes, type SettledRefresh } from '@/lib/portfolio/refresh-settled';

describe('partitionSettledRefreshes', () => {
    it('separa escritas, sin cotización y fallidas aunque se mezclen', () => {
        const settled: SettledRefresh[] = [
            { status: 'fulfilled', value: { symbol: 'SAN', written: true } },
            { status: 'fulfilled', value: { symbol: 'IBE', written: false } },
            { status: 'rejected', reason: new Error('500') },
        ];
        expect(partitionSettledRefreshes(['SAN', 'IBE', 'REP'], settled)).toEqual({
            updated: ['SAN'], skipped: ['IBE'], failed: ['REP'],
        });
    });
    it('un fallo de una no esconde las que sí se guardaron (el fallo de all)', () => {
        const settled: SettledRefresh[] = [
            { status: 'fulfilled', value: { symbol: 'A', written: true } },
            { status: 'rejected' },
        ];
        const r = partitionSettledRefreshes(['A', 'B'], settled);
        expect(r.updated).toEqual(['A']);
        expect(r.failed).toEqual(['B']);
    });
    it('lista vacía devuelve tres listas vacías', () => {
        expect(partitionSettledRefreshes([], [])).toEqual({ updated: [], skipped: [], failed: [] });
    });
});
