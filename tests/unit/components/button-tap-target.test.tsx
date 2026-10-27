import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button } from '@/components/ui/button';

describe('Button: área táctil de 44 px en móvil', () => {
    for (const size of ['default', 'sm', 'icon', 'lg'] as const) {
        it(`talla ${size}`, () => {
            render(<Button size={size}>Acción</Button>);
            const cls = screen.getByRole('button', { name: 'Acción' }).className;
            // lg ya mide h-11 (44 px); el resto necesita el mínimo en móvil.
            expect(size === 'lg' ? cls.includes('h-11') : cls.includes('max-sm:min-h-11')).toBe(true);
        });
    }
    it('icon también llega a 44 px de ancho en móvil', () => {
        render(<Button size="icon" aria-label="Cerrar">x</Button>);
        expect(screen.getByRole('button', { name: 'Cerrar' }).className).toContain('max-sm:min-w-11');
    });
    it('una clase min-h propia del consumidor sigue ganando', () => {
        render(<Button className="min-h-0">Compacto</Button>);
        expect(screen.getByRole('button', { name: 'Compacto' }).className).toContain('min-h-0');
    });
});
