import { describe, expect, it } from 'vitest';
import { valueRankKey, valueRankSummary } from '@/lib/watchlist/value-rank';
import es from '@/lib/i18n/messages/es/watchlist.json';
import en from '@/lib/i18n/messages/en/watchlist.json';

describe('puesto relativo por valor justo (sustituye a infravalorada/sobrevalorada)', () => {
    it('quintil 1 es el 20 % más barato y 5 el más caro', () => {
        expect(valueRankKey({ quintile: 1, cheaper_than_pct: 92, peers: 300 })).toBe('watchlist.page.fairValue.rankQ1');
        expect(valueRankKey({ quintile: 5, cheaper_than_pct: 4, peers: 300 })).toBe('watchlist.page.fairValue.rankQ5');
        expect(valueRankKey(null)).toBeNull();
        expect(valueRankKey({ quintile: 0, cheaper_than_pct: 0, peers: 300 })).toBeNull();
    });

    it('el resumen cuenta los extremos y los comparables', () => {
        const ranks = [
            { quintile: 1, cheaper_than_pct: 90, peers: 310 },
            { quintile: 3, cheaper_than_pct: 50, peers: 310 },
            { quintile: 5, cheaper_than_pct: 10, peers: 310 },
            { quintile: 5, cheaper_than_pct: 2, peers: 310 },
            null,
        ];
        expect(valueRankSummary(ranks)).toEqual({ cheap: 1, dear: 2, peers: 310, ranked: 4 });
    });

    it('el resumen ya no dice infravaloradas ni sobrevaloradas', () => {
        expect(es.page.fairValue.summary).not.toMatch(/infravalorad|sobrevalorad/);
        expect(en.page.fairValue.summary).not.toMatch(/undervalued|overvalued/);
        for (const q of [1, 2, 3, 4, 5]) {
            const key = `rankQ${q}` as keyof typeof es.page.fairValue;
            expect(es.page.fairValue[key]).toBeTruthy();
            expect(en.page.fairValue[key]).toBeTruthy();
        }
    });
});
