import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/dca-watch-card.actions', () => ({ getDcaWatchCard: vi.fn(async () => null) }));
vi.mock('@/components/watchlist/DcaWatchCard', () => ({ default: () => <p>Tarjeta fixture</p> }));
import DcaWatchCardToggle from '@/components/watchlist/DcaWatchCardToggle';

describe('DcaWatchCardToggle en la lista compacta', () => {
    it('cerrado no fuerza salto de línea; abierto ocupa todo el ancho', () => {
        // Captura 390px (2026-11-14): el wrapper w-full bajaba «Tarjeta DCA» a
        // otra línea incluso en escritorio y la lista no quedaba en una línea.
        render(<DcaWatchCardToggle symbol="TEST" />);
        const button = screen.getByRole('button');
        expect(button.parentElement?.className).not.toContain('w-full');
        fireEvent.click(button);
        // Abierto: la tarjeta necesita el ancho completo debajo de la línea.
        expect(button.parentElement?.className).toContain('w-full');
    });
});
