import { useEffect, useRef } from 'react';

/** Reveal the URL-selected tab without moving page scroll or keyboard focus. */
export function useActiveTabVisible(activeTab: string) {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const viewport = ref.current;
        const selected = viewport?.querySelector<HTMLElement>('[role="tab"][data-state="active"]');
        if (!viewport || !selected) return;
        const outer = viewport.getBoundingClientRect();
        const inner = selected.getBoundingClientRect();
        const left = outer.left + viewport.clientLeft;
        const right = left + viewport.clientWidth;
        const offset = inner.left < left ? Math.floor(inner.left - left)
            : inner.right > right ? Math.ceil(inner.right - right) : 0;
        if (offset) viewport.scrollLeft += offset;
    }, [activeTab]);
    return ref;
}
