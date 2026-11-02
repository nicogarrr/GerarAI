import { describe, expect, it } from 'vitest';
import { emptyWatchlistEntry } from '@/lib/watchlist/entry-fallback';

describe('emptyWatchlistEntry', () => {
    it('preserves master identity and currency, never fabricates quotes', () => {
        const row = emptyWatchlistEntry('VOD.L', { name: 'Vodafone', exchange: 'LSE', currency: 'GBp' } as Parameters<typeof emptyWatchlistEntry>[1], 'VOD.L');
        expect(row).toMatchObject({ symbol: 'VOD.L', name: 'Vodafone', exchange: 'LSE', currency: 'GBp', quoteSymbol: 'VOD.L', price: null, change: null, changePercent: null, marketCap: null, peRatio: null, priceKind: null, priceAsOf: null, marketCapDerived: false, metricsNotApplicable: false });
    });
    it('unknown issuer and network failure remain unknown, not USD or zero', () => {
        const row = emptyWatchlistEntry('UNKNOWN', null, null);
        expect(row.name).toBe('UNKNOWN');
        expect(row.exchange).toBeNull();
        expect(row.currency).toBeNull();
        expect(row.price).toBeNull();
        expect(row.quoteSymbol).toBeNull();
    });
});
