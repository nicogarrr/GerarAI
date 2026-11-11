import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { trackBrowserHistory } from '@/lib/nav/browser-history';
import { historyBackSteps, inAppHistoryStore } from '@/lib/nav/in-app-history';

let cleanup: () => void;
const stack = () => inAppHistoryStore.getSnapshot();
const traverse = (steps: number) => new Promise<void>(resolve => {
    window.addEventListener('popstate', () => setTimeout(resolve, 0), { once: true });
    window.history.go(steps);
});
const anchor = (hash: string) => new Promise<void>(resolve => {
    window.addEventListener('hashchange', () => resolve(), { once: true });
    window.location.hash = hash;
});
beforeEach(() => {
    inAppHistoryStore.reset();
    window.history.replaceState({ nextField: 'preserve' }, '', '/watchlist');
    cleanup = trackBrowserHistory(window);
});
afterEach(() => cleanup());

describe('real browser history entries, independent of URL equality', () => {
    it('preserves PUSH A→B→A and POP/forward identities', async () => {
        window.history.pushState({}, '', '/research/MSFT');
        window.history.pushState({}, '', '/watchlist');
        expect(stack()).toEqual(['/watchlist', '/research/MSFT', '/watchlist']);
        await traverse(-1);
        expect(stack()).toEqual(['/watchlist', '/research/MSFT']);
        await traverse(1);
        expect(stack()).toEqual(['/watchlist', '/research/MSFT', '/watchlist']);
    });
    it('repeated native anchors return all the way to watchlist', async () => {
        window.history.pushState({}, '', '/research/MSFT');
        await anchor('#analistas');
        await anchor('#historial-analistas');
        await anchor('#analistas');
        expect(historyBackSteps(stack())).toBe(4);
        await traverse(-historyBackSteps(stack()));
        expect(window.location.pathname).toBe('/watchlist');
        expect(window.location.hash).toBe('');
        expect(stack()).toEqual(['/watchlist']);
    });
    it('REPLACE changes one entry without introducing a browser step', async () => {
        window.history.pushState({ nextField: 'x' }, '', '/research/MSFT');
        window.history.replaceState({ nextField: 'y' }, '', '/research/MSFT?view=tesis');
        expect(stack()).toEqual(['/watchlist', '/research/MSFT?view=tesis']);
        expect(window.history.state.nextField).toBe('y');
        await traverse(-1);
        expect(stack()).toEqual(['/watchlist']);
        expect(window.history.state.nextField).toBe('preserve');
    });
    it('a PUSH after POP discards the old forward branch', async () => {
        window.history.pushState(null, '', '/a');
        window.history.pushState(null, '', '/b');
        await traverse(-1);
        window.history.pushState(null, '', '/c');
        expect(stack()).toEqual(['/watchlist', '/a', '/c']);
    });
    it('counts identical URL PUSH entries instead of collapsing them', () => {
        window.history.pushState(null, '', '/research/MSFT');
        window.history.pushState(null, '', '/research/MSFT');
        expect(historyBackSteps(stack())).toBe(2);
    });
    it('caps established entries and cannot infer an unknown entry origin', async () => {
        for (let index = 0; index < 52; index++) window.history.pushState(null, '', `/t${index}`);
        expect(stack()).toHaveLength(50);
        await traverse(-51);
        expect(stack()).toHaveLength(1);
        expect(historyBackSteps(stack())).toBe(0);
    });
    it('direct mounts with anchors never manufacture an external origin', async () => {
        cleanup();
        window.history.replaceState(null, '', '/research/MSFT');
        cleanup = trackBrowserHistory(window);
        await anchor('#analistas');
        expect(historyBackSteps(stack())).toBe(0);
    });
    it('cleanup restores methods and stops event tracking', () => {
        cleanup();
        const before = stack();
        window.history.pushState(null, '', '/untracked');
        window.dispatchEvent(new PopStateEvent('popstate'));
        expect(stack()).toBe(before);
    });
});
