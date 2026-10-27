import React from 'react';
import { render } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useActiveTabVisible } from '@/components/portfolio/use-active-tab-visible';

function Fixture({ active }: { active: string }) {
    const ref = useActiveTabVisible(active);
    return <div ref={ref} data-testid="viewport"><button role="tab" data-state="active">{active}</button></div>;
}

it('reveals a selected tab to the right on direct URL entry and to the left on URL changes', () => {
    let rect = { left: 480, right: 610 };
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function () {
        return (this.getAttribute('role') === 'tab' ? rect : { left: 16, right: 374 }) as DOMRect;
    });
    const { getByTestId, rerender } = render(<Fixture active="posiciones" />);
    const viewport = getByTestId('viewport');
    expect(viewport.scrollLeft).toBe(236);
    rect = { left: -220, right: -100 };
    rerender(<Fixture active="resumen" />);
    expect(viewport.scrollLeft).toBe(0);
});

it('does not move an already visible tab or steal focus', () => {
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ left: 16, right: 374 } as DOMRect);
    const { getByTestId } = render(<Fixture active="resumen" />);
    expect(getByTestId('viewport').scrollLeft).toBe(0);
    expect(document.activeElement).toBe(document.body);
});
