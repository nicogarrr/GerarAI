import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import FollowButton from '@/components/screener/FollowButton';

vi.mock('@/lib/actions/watchlist-toggle.actions', () => ({
    addToWatchlist: vi.fn(),
    removeFromWatchlist: vi.fn(),
}));
vi.mock('@/lib/types/errors', () => ({
    getFriendlyErrorMessage: (e: unknown) => String(e),
}));
vi.mock('@/components/ui/toast', () => ({
    showErrorToast: vi.fn(),
}));

describe('FollowButton compacto (cabecera de ficha)', () => {
    it('en móvil el estado «siguiendo» lleva etiqueta visible, no solo una ✓', () => {
        render(<FollowButton compact symbol="ASTS" isFollowed stateUnknown={false} />);
        expect(screen.getByText('Siguiendo')).toBeTruthy();
    });

    it('sin seguir muestra «Seguir» visible también en móvil', () => {
        render(<FollowButton compact symbol="ASTS" isFollowed={false} stateUnknown={false} />);
        expect(screen.getAllByText('Seguir').length).toBeGreaterThan(0);
    });

    // WCAG 2.5.3 (axe label-content-name-mismatch): el nombre accesible debe
    // contener el texto que se ve, en móvil («Siguiendo») y en escritorio.
    it.each([
        ['siguiendo', { isFollowed: true, stateUnknown: false }],
        ['sin seguir', { isFollowed: false, stateUnknown: false }],
        ['estado desconocido', { isFollowed: false, stateUnknown: true }],
    ])('el nombre accesible incluye cada texto visible (%s)', (_label, props) => {
        render(<FollowButton compact symbol="ASTS" {...props} />);
        const button = screen.getByRole('button');
        const ariaLabel = button.getAttribute('aria-label');
        const visibleTexts = Array.from(button.querySelectorAll('span')).map((span) => span.textContent ?? '');
        expect(visibleTexts.length).toBeGreaterThan(0);
        for (const text of visibleTexts) {
            if (ariaLabel !== null) expect(ariaLabel.toLowerCase()).toContain(text.toLowerCase());
        }
    });
});
