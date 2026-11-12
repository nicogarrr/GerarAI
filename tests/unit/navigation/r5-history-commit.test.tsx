import { useInsertionEffect, useSyncExternalStore } from 'react';
import { act, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { inAppHistoryStore } from '@/lib/nav/in-app-history';

function Subscriber() {
    const stack = useSyncExternalStore(inAppHistoryStore.subscribe, inAppHistoryStore.getSnapshot, inAppHistoryStore.getServerSnapshot);
    return <output>{stack.join(' → ')}</output>;
}
function NextHistoryCommit({ url }: { url: string }) {
    // Next changes browser history inside its insertion effect. Navigation
    // currententrychange fires synchronously there, before commit completes.
    useInsertionEffect(() => { inAppHistoryStore.replaceStack(['/watchlist', url]); }, [url]);
    return null;
}
it('publishes navigation changes outside Next insertion effects without losing the latest stack', async () => {
    inAppHistoryStore.reset();
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    const view = render(<><Subscriber /><NextHistoryCommit url="/a" /></>);
    await act(async () => {});
    view.rerender(<><Subscriber /><NextHistoryCommit url="/research/MSFT/tesis" /></>);
    await act(async () => {});
    expect(screen.getByText('/watchlist → /research/MSFT/tesis')).toBeTruthy();
    expect(errors.mock.calls.flat().join(' ')).not.toMatch(/useInsertionEffect must not schedule updates/);
    errors.mockRestore();
    inAppHistoryStore.reset();
});
it('unsubscribed listeners are not called by a queued notification', async () => {
    const listener = vi.fn();
    const unsubscribe = inAppHistoryStore.subscribe(listener);
    inAppHistoryStore.replaceStack(['/a']);
    inAppHistoryStore.replaceStack(['/a', '/b']);
    unsubscribe();
    await Promise.resolve();
    expect(listener).not.toHaveBeenCalled();
    expect(inAppHistoryStore.getSnapshot()).toEqual(['/a', '/b']);
    inAppHistoryStore.reset();
});
