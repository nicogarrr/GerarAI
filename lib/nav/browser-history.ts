import { inAppHistoryStore } from './in-app-history';

type NavigationEntry = { key: string; index: number; url: string | null };
type NavigationHistory = EventTarget & { currentEntry: NavigationEntry | null };

/** Only browser-owned entry identities can establish PUSH versus traversal.
 * Without Navigation API support, use the original safe link, never guess.
 */
export function trackBrowserHistory(win: Window): () => void {
    const navigation = (win as Window & { navigation?: NavigationHistory }).navigation;
    inAppHistoryStore.replaceStack([]);
    if (!navigation?.currentEntry) return () => {};
    const entries = new Map<number, NavigationEntry>();
    const sync = (event?: Event) => {
        const kind = (event as Event & { navigationType?: string } | undefined)?.navigationType;
        const entry = navigation.currentEntry;
        if (!entry?.url) {
            entries.clear();
            inAppHistoryStore.replaceStack([]);
            return;
        }
        const known = entries.get(entry.index);
        // Unknown traversal is not a PUSH, even if its index is adjacent.
        if (kind === 'traverse' && known?.key !== entry.key) entries.clear();
        if (kind === 'push') {
            for (const index of entries.keys()) if (index >= entry.index) entries.delete(index);
        }
        entries.set(entry.index, entry);
        while (entries.size > 50) entries.delete(Math.min(...entries.keys()));
        const stack = [...entries.values()].filter(item => item.index <= entry.index).sort((a, b) => a.index - b.index).map(item => {
            const url = new URL(item.url!);
            return url.pathname + url.search + url.hash;
        });
        inAppHistoryStore.replaceStack(stack);
    };
    sync();
    navigation.addEventListener('currententrychange', sync);
    return () => navigation.removeEventListener('currententrychange', sync);
}
