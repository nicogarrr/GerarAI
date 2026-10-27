import { act, renderHook } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { useOnlineStatus } from '@/hooks/useOnlineStatus';

function setOnline(value: boolean) {
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(value);
}

function Probe() {
    return <span>{useOnlineStatus() ? 'online' : 'offline'}</span>;
}

describe('useOnlineStatus', () => {
    it('lee navigator.onLine al montar', () => {
        setOnline(false);
        const { result } = renderHook(() => useOnlineStatus());
        expect(result.current).toBe(false);
    });

    it('sigue los eventos online/offline', () => {
        setOnline(true);
        const { result } = renderHook(() => useOnlineStatus());
        expect(result.current).toBe(true);
        setOnline(false);
        act(() => {
            window.dispatchEvent(new Event('offline'));
        });
        expect(result.current).toBe(false);
        setOnline(true);
        act(() => {
            window.dispatchEvent(new Event('online'));
        });
        expect(result.current).toBe(true);
    });

    it('en el servidor asume conexión (sin aviso falso en el HTML inicial)', () => {
        setOnline(false);
        expect(renderToString(<Probe />)).toContain('online');
    });

    it('al desmontar quita los listeners', () => {
        const remove = vi.spyOn(window, 'removeEventListener');
        const { unmount } = renderHook(() => useOnlineStatus());
        unmount();
        const types = remove.mock.calls.map(([type]) => type);
        expect(types).toEqual(expect.arrayContaining(['online', 'offline']));
    });
});
