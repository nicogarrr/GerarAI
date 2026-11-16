export type PreparingStatus = 'preparing' | 'ready' | 'unavailable';
type Entry = {
    attempts: number;
    deadline: number;
    done: boolean;
    pending: boolean;
    timer?: ReturnType<typeof setTimeout>;
    listeners: Map<symbol, () => void>;
};
const entries = new Map<string, Entry>();
const DELAY = 30_000;
const MAX_ATTEMPTS = 20;

/** Shared across card instances and React remounts. No settled financial data is cached. */
export function watchPreparing(key: string, read: () => Promise<PreparingStatus>, ready: () => void): () => void {
    let entry = entries.get(key);
    if (!entry) {
        entry = { attempts: 0, deadline: Date.now() + DELAY * MAX_ATTEMPTS, done: false, pending: false, listeners: new Map() };
        entries.set(key, entry);
    }
    const state = entry;
    const id = Symbol(key);
    state.listeners.set(id, ready);
    const schedule = () => {
        if (state.timer || state.pending || state.done || !state.listeners.size || state.attempts >= MAX_ATTEMPTS || Date.now() >= state.deadline) return;
        state.timer = setTimeout(async () => {
            state.timer = undefined;
            if (Date.now() >= state.deadline) { state.done = true; return; }
            if (document.visibilityState !== 'visible') { schedule(); return; }
            state.pending = true;
            state.attempts += 1;
            let status: PreparingStatus = 'unavailable';
            try { status = await read(); } catch { /* A failed read is not completion. */ }
            state.pending = false;
            if (Date.now() >= state.deadline) { state.done = true; return; }
            // Respect failures/rate limits: do not manufacture a fresh retry loop.
            if (status === 'unavailable') state.done = true;
            if (status === 'ready') {
                // One refresh, not one per mounted copy of the same card.
                const callback = state.listeners.values().next().value;
                if (callback) { state.done = true; callback(); }
            }
            schedule();
        }, DELAY);
    };
    schedule();
    return () => {
        state.listeners.delete(id);
        if (!state.listeners.size && state.timer) {
            clearTimeout(state.timer);
            state.timer = undefined;
        }
    };
}
