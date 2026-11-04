import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import MobileCollapse from '@/components/ui/mobile-collapse';

/**
 * Desplegables (dueño, 4-nov-2026): «tendrán que desplegarse dentro» y «¿por qué aparece un hueco?».
 * Cabecera y contenido viven en UNA tarjeta: sin margen entre ambos y sin la tarjeta propia del hijo en móvil.
 */
describe('MobileCollapse: una sola tarjeta', () => {
    it('cabecera y contenido comparten contenedor, sin hueco entre medias', () => {
        render(<MobileCollapse title="Lectura"><section className="rounded-xl border p-4">Contenido</section></MobileCollapse>);
        const button = screen.getByRole('button', { name: /Lectura/ });
        const body = document.getElementById(button.getAttribute('aria-controls')!)!;
        const card = screen.getByTestId('mobile-collapse');
        expect(button.parentElement).toBe(card);
        expect(body.parentElement).toBe(card);
        expect(card.className).toContain('max-md:border');
        expect(card.className).toContain('max-md:rounded-xl');
        expect(card.className).toContain('max-md:overflow-hidden');
        // El hueco venía de `mt-3` en el cuerpo; el botón ya no es una tarjeta aparte.
        expect(body.className).not.toMatch(/(^|\s)(mt|my|space-y)-/);
        expect(button.className).not.toMatch(/(^|\s)(border|rounded-xl)(\s|$)/);
        // La tarjeta del hijo pierde borde y radio solo en móvil.
        expect(body.className).toContain('max-md:*:border-0!');
        expect(body.className).toContain('max-md:*:rounded-none!');
    });

    it('cerrado en móvil y visible desde md; abre y cierra con aria-expanded', () => {
        render(<MobileCollapse title="Señales"><p>Dato</p></MobileCollapse>);
        const button = screen.getByRole('button', { name: /Señales/ });
        const body = document.getElementById(button.getAttribute('aria-controls')!)!;
        expect(button).toHaveAttribute('aria-expanded', 'false');
        expect(body.className).toContain('hidden');
        expect(body.className).toContain('md:block');
        fireEvent.click(button);
        expect(button).toHaveAttribute('aria-expanded', 'true');
        expect(body.className).not.toMatch(/(^|\s)hidden(\s|$)/);
        expect(screen.getByTestId('mobile-collapse')).toHaveAttribute('data-open', 'true');
        fireEvent.click(button);
        expect(button).toHaveAttribute('aria-expanded', 'false');
    });

    it('inset: dentro de otra tarjeta solo pinta la línea superior, sin marco propio', () => {
        render(<MobileCollapse inset title="Lectura técnica"><aside>Niveles</aside></MobileCollapse>);
        const card = screen.getByTestId('mobile-collapse');
        expect(card.className).toContain('max-md:border-t');
        expect(card.className).not.toContain('max-md:rounded-xl');
        expect(card.className).not.toMatch(/max-md:border(\s|$)/);
    });
});
