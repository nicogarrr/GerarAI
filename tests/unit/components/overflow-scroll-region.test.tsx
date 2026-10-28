import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { OverflowScrollRegion } from '@/components/ui/overflow-scroll-region';

function setOverflow(el: Element, scrollWidth: number, clientWidth: number, scrollLeft = 0) {
    Object.defineProperty(el, 'scrollWidth', { value: scrollWidth, configurable: true });
    Object.defineProperty(el, 'clientWidth', { value: clientWidth, configurable: true });
    Object.defineProperty(el, 'scrollLeft', { value: scrollLeft, configurable: true, writable: true });
}

describe('OverflowScrollRegion', () => {
    it('sin overflow real no anuncia scroll que no existe', () => {
        render(<OverflowScrollRegion label="Tabla"><div>contenido</div></OverflowScrollRegion>);
        expect(screen.queryByText(/Desliza para ver más/)).not.toBeInTheDocument();
        expect(screen.getByRole('region', { name: 'Tabla' })).not.toHaveAttribute('aria-describedby');
    });
    it('con overflow anuncia la pista y la enlaza con aria-describedby; al llegar al final desaparece', () => {
        render(<OverflowScrollRegion label="Tabla" hint="Desliza para ver más secciones"><div>contenido</div></OverflowScrollRegion>);
        const region = screen.getByRole('region', { name: 'Tabla' });
        setOverflow(region, 500, 100);
        fireEvent.scroll(region);
        const hint = screen.getByText(/Desliza para ver más secciones/);
        expect(hint).toBeInTheDocument();
        expect(region).toHaveAttribute('aria-describedby', hint.id);
        // Al llegar al final ya no queda contenido a la derecha: la pista sobra.
        setOverflow(region, 500, 100, 400);
        fireEvent.scroll(region);
        expect(screen.queryByText(/Desliza para ver más secciones/)).not.toBeInTheDocument();
        expect(region).not.toHaveAttribute('aria-describedby');
    });
    it('la región es enfocable con teclado (tabIndex 0)', () => {
        render(<OverflowScrollRegion label="Tabla"><div>x</div></OverflowScrollRegion>);
        expect(screen.getByRole('region', { name: 'Tabla' })).toHaveAttribute('tabindex', '0');
    });
});
