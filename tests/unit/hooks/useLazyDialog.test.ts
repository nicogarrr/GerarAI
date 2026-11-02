import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useLazyDialog } from '@/hooks/useLazyDialog';
describe('useLazyDialog', () => {
    it('mounts only after first open and keeps mounted state after closing', () => {
        const { result } = renderHook(() => useLazyDialog());
        expect([result.current.open, result.current.openedOnce]).toEqual([false, false]);
        act(() => result.current.onOpenChange(true));
        expect([result.current.open, result.current.openedOnce]).toEqual([true, true]);
        act(() => result.current.onOpenChange(false));
        expect([result.current.open, result.current.openedOnce]).toEqual([false, true]);
        act(() => result.current.openDialog());
        expect([result.current.open, result.current.openedOnce]).toEqual([true, true]);
        act(() => result.current.setOpen(false));
        expect(result.current.openedOnce).toBe(true);
    });
    it('programmatic opening also mounts the dialog', () => {
        const { result } = renderHook(() => useLazyDialog());
        act(() => result.current.openDialog());
        expect([result.current.open, result.current.openedOnce]).toEqual([true, true]);
    });
});
