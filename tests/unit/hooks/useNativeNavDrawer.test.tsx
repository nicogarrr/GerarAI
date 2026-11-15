import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useNativeNavDrawer } from '@/hooks/useNativeNavDrawer';

let dialog: HTMLDialogElement;
let trigger: HTMLButtonElement;
let closeButton: HTMLButtonElement;
let breakpoint: (() => void) | undefined;
let matches = false;
const onClose = vi.fn();
const show = vi.fn(function (this: HTMLDialogElement) { this.open = true; });
const close = vi.fn(function (this: HTMLDialogElement) {
    if (!this.open) return;
    this.open = false;
    this.dispatchEvent(new Event('close'));
});

beforeEach(() => {
    matches = false;
    breakpoint = undefined;
    vi.clearAllMocks();
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: show });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: close });
    dialog = document.createElement('dialog');
    trigger = document.createElement('button');
    closeButton = document.createElement('button');
    dialog.append(closeButton);
    document.body.append(trigger, dialog);
    vi.stubGlobal('matchMedia', vi.fn(() => ({
        get matches() { return matches; },
        addEventListener: (_: string, cb: () => void) => { breakpoint = cb; },
        removeEventListener: vi.fn(),
    })));
});
afterEach(() => { dialog.remove(); trigger.remove(); });
const options = () => ({ active: true, onClose, dialogRef: { current: dialog }, closeButtonRef: { current: closeButton }, triggerRef: { current: trigger } });

describe('useNativeNavDrawer React wiring (not native focus/inert simulation)', () => {
    it('does nothing while inactive or without a mounted dialog', () => {
        const { rerender } = renderHook(({ active, mounted }) => useNativeNavDrawer({ ...options(), active, dialogRef: { current: mounted ? dialog : null } }), { initialProps: { active: false, mounted: true } });
        expect(show).not.toHaveBeenCalled();
        rerender({ active: true, mounted: false });
        expect(show).not.toHaveBeenCalled();
    });
    it('does not reopen an already-open dialog and ignores stale close events', () => {
        dialog.open = true;
        renderHook(() => useNativeNavDrawer(options()));
        expect(show).not.toHaveBeenCalled();
        act(() => { dialog.dispatchEvent(new Event('close')); });
        expect(onClose).not.toHaveBeenCalled();
    });
    it('uses native light-dismiss when supported and cleans up an open dialog', () => {
        Object.defineProperty(HTMLDialogElement.prototype, 'closedBy', { configurable: true, value: 'any' });
        try {
            const { unmount } = renderHook(() => useNativeNavDrawer(options()));
            expect(dialog.open).toBe(true);
            act(() => { breakpoint?.(); }); // Below md: no close.
            expect(dialog.open).toBe(true);
            unmount();
            expect(dialog.open).toBe(false);
            expect(onClose).not.toHaveBeenCalled();
        } finally { Reflect.deleteProperty(HTMLDialogElement.prototype, 'closedBy'); }
    });
    it('does not blur a visible invoker and uses the latest onClose', () => {
        vi.spyOn(trigger, 'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
        const next = vi.fn();
        const refs = options();
        const { rerender } = renderHook(({ cb }) => useNativeNavDrawer({ ...refs, onClose: cb }), { initialProps: { cb: onClose } });
        rerender({ cb: next });
        expect(show).toHaveBeenCalledTimes(1);
        trigger.focus();
        act(() => { dialog.close(); });
        expect(next).toHaveBeenCalledTimes(1);
        expect(onClose).not.toHaveBeenCalled();
        expect(document.activeElement).toBe(trigger);
    });
    it('closes at md and blurs an invoker hidden by the breakpoint', () => {
        renderHook(() => useNativeNavDrawer(options()));
        trigger.focus();
        matches = true;
        act(() => { breakpoint?.(); });
        expect(dialog.open).toBe(false);
        expect(document.activeElement).not.toBe(trigger);
        expect(onClose).toHaveBeenCalledTimes(1);
        act(() => { breakpoint?.(); });
        expect(onClose).toHaveBeenCalledTimes(1);
    });
    it('closes if the lazy drawer mounts after the viewport already crossed md', () => {
        matches = true;
        renderHook(() => useNativeNavDrawer(options()));
        expect(dialog.open).toBe(false);
        expect(onClose).toHaveBeenCalledTimes(1);
    });
    it('supports absent optional controls', () => {
        renderHook(() => useNativeNavDrawer({ ...options(), closeButtonRef: { current: null }, triggerRef: { current: null } }));
        act(() => { dialog.close(); });
        expect(onClose).toHaveBeenCalledTimes(1);
    });
});
