import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { trackBrowserHistory } from '@/lib/nav/browser-history';
import { historyBackSteps, inAppHistoryStore } from '@/lib/nav/in-app-history';
let cleanup: () => void;
let navigation: EventTarget & { currentEntry: { key: string; index: number; url: string } | null };
const stack = () => inAppHistoryStore.getSnapshot();
const entry = (key: string, index: number, path: string, kind = 'push') => {
    navigation.currentEntry = { key, index, url: `http://localhost${path}` };
    navigation.dispatchEvent(Object.assign(new Event('currententrychange'), { navigationType: kind }));
};
beforeEach(() => {
    navigation = Object.assign(new EventTarget(), { currentEntry: { key: 'origin', index: 3, url: 'http://localhost/watchlist' } });
    vi.stubGlobal('navigation', navigation);
    cleanup = trackBrowserHistory(window);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe('browser-owned entry identity and navigation type', () => {
    it('preserves A→B→A PUSH, POP and forward', () => {
        entry('B', 4, '/research/MSFT'); entry('A2', 5, '/watchlist');
        expect(stack()).toEqual(['/watchlist', '/research/MSFT', '/watchlist']);
        entry('B', 4, '/research/MSFT', 'traverse');
        expect(stack()).toEqual(['/watchlist', '/research/MSFT']);
        entry('A2', 5, '/watchlist', 'traverse');
        expect(stack()).toHaveLength(3);
    });
    it('counts repeated anchors and identical URL PUSHes', () => {
        entry('b', 4, '/research/MSFT'); entry('c', 5, '/research/MSFT#a');
        entry('d', 6, '/research/MSFT#h'); entry('e', 7, '/research/MSFT#a');
        expect(historyBackSteps(stack())).toBe(4);
        entry('f', 8, '/research/MSFT#a');
        expect(historyBackSteps(stack())).toBe(5);
    });
    it('REPLACE keeps one step and a new PUSH after POP discards forward entries', () => {
        entry('b', 4, '/b'); entry('r', 4, '/r', 'replace'); entry('c', 5, '/c');
        entry('r', 4, '/r', 'traverse'); entry('d', 5, '/d');
        expect(stack()).toEqual(['/watchlist', '/r', '/d']);
    });
    it('unknown POP before mount resets, including an adjacent index and same URL', () => {
        entry('b', 4, '/research/MSFT');
        entry('unstamped', 2, '/pretracker', 'traverse');
        expect(stack()).toEqual(['/pretracker']);
        expect(historyBackSteps(stack())).toBe(0);
        entry('unknown-forward', 3, '/watchlist', 'traverse');
        expect(stack()).toEqual(['/watchlist']);
    });
    it('caps entries and resets missing current entry', () => {
        for (let i = 4; i < 60; i++) entry(String(i), i, `/t${i}`);
        expect(stack()).toHaveLength(50);
        navigation.currentEntry = null;
        navigation.dispatchEvent(new Event('currententrychange'));
        expect(stack()).toEqual([]);
    });
    it('has a safe fallback without Navigation API and cleans up listeners', () => {
        cleanup(); entry('b', 4, '/b'); expect(stack()).toEqual(['/watchlist']);
        vi.stubGlobal('navigation', undefined);
        cleanup = trackBrowserHistory(window);
        expect(stack()).toEqual([]);
    });
});
