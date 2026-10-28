import { describe, it, expect } from 'vitest';
import { attentionDcaItems } from '@/lib/overview/home-attention';
import type { DcaSignalsResponse } from '@/lib/dca/types';
const now = new Date('2026-10-28T17:00:00Z');
function data(over = {}, state = {}, item = {}) {
    return { items: [{ symbol: 'UBER', in_watchlist: true, effective_min_level: 3,
        state: { level: 4, signal_date: '2026-10-27', status: 'forming', ...state }, ...item }], ...over } as unknown as DcaSignalsResponse;
}
describe('home attention DCA policy', () => {
    it('uses actual effective minimum and date, not alert delivery status', () => {
        expect(attentionDcaItems(data(), now)).toMatchObject([{ symbol: 'UBER', level: 4, threshold: 3, forming: true }]);
        expect(attentionDcaItems(data({}, { level: 2 }), now)).toEqual([]);
    });
    it('supports new directional contract without inventing missing preferences', () => {
        expect(attentionDcaItems(data({ alert_policy: 'directional', up_min_level: 4 }), now)).toHaveLength(1);
        expect(attentionDcaItems(data({ alert_policy: 'directional' }), now)).toEqual([]);
        expect(attentionDcaItems(data({ alert_policy: 'directional', up_min_level: 0 }), now)).toEqual([]);
    });
    it.each([{ stale: true }, { signal_date: '2026-09-27' }, { signal_date: '2026-10-29' }, { signal_date: '' }, { level: 5 }, { level: 3.5 }, { status: 'pending' }])('rejects invalid or stale state %o', state => {
        expect(attentionDcaItems(data({}, state), now)).toEqual([]);
    });
    it.each([0, null, 5, 1.5])('rejects missing/disabled/invalid minimum %s', min => {
        expect(attentionDcaItems(data({}, {}, { effective_min_level: min }), now)).toEqual([]);
    });
    it('only followed or owned tickers; no uncomputed signal', () => {
        expect(attentionDcaItems(data({}, {}, { in_watchlist: false }), now)).toEqual([]);
        expect(attentionDcaItems(data({}, {}, { state: null }), now)).toEqual([]);
    });
});
