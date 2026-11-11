import { inAppHistoryStore } from './in-app-history';

const KEY = '__geraraiHistoryEntry';
let sequence = 0;

/** Track entry identity, not URL identity: repeated links are still PUSHes. */
export function trackBrowserHistory(win: Window): () => void {
    const history = win.history;
    const push = history.pushState;
    const replace = history.replaceState;
    const url = () => win.location.pathname + win.location.search + win.location.hash;
    type Entry = { key: number; url: string };
    let entries: Entry[] = [];
    let cursor = -1;
    const publish = () => inAppHistoryStore.replaceStack(entries.slice(0, cursor + 1).map(entry => entry.url));
    const stamp = (state: unknown, key: number) => ({ ...(state && typeof state === 'object' ? state : {}), [KEY]: key });
    const add = () => {
        const entry = { key: ++sequence, url: url() };
        replace.call(history, stamp(history.state, entry.key), '');
        entries = [...entries.slice(0, cursor + 1), entry].slice(-50);
        cursor = entries.length - 1;
        publish();
    };
    add(); // A new mount has no established origin outside this tracker.
    const pushState: History['pushState'] = function (state, unused, target) {
        push.call(history, state, unused, target);
        add();
    };
    const replaceState: History['replaceState'] = function (state, unused, target) {
        const entry = entries[cursor];
        replace.call(history, stamp(state, entry.key), unused, target);
        entry.url = url();
        publish();
    };
    const sync = () => {
        const key = history.state?.[KEY];
        const index = entries.findIndex(entry => entry.key === key);
        if (index !== -1 && entries[index].url === url()) {
            cursor = index;
            publish();
        } else {
            // Native anchor PUSH has no stamp. An unknown POP is not a proven
            // internal origin, so discard the tracked stack before stamping it.
            if (key !== undefined) { entries = []; cursor = -1; }
            add();
        }
    };
    history.pushState = pushState;
    history.replaceState = replaceState;
    win.addEventListener('popstate', sync);
    win.addEventListener('hashchange', sync);
    return () => {
        if (history.pushState === pushState) history.pushState = push;
        if (history.replaceState === replaceState) history.replaceState = replace;
        win.removeEventListener('popstate', sync);
        win.removeEventListener('hashchange', sync);
    };
}
