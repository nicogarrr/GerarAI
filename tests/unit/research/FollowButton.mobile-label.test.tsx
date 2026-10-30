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

    it('sin aria-label: el nombre accesible es el texto visible (label-content-name-mismatch a 375 px)', () => {
        // Barrido axe 30-oct-2026, /research/MSFT a 375 px: el compacto
        // mostraba «Siguiendo» pero el aria-label decía «Dejar de seguir»
        // (violación seria WCAG 2.5.3). El nombre sale del contenido: en cada
        // breakpoint solo un span es visible y el otro lleva display:none.
        const { rerender } = render(<FollowButton compact symbol="ASTS" isFollowed stateUnknown={false} />);
        expect(screen.getByRole('button')).not.toHaveAttribute('aria-label');
        rerender(<FollowButton compact symbol="ASTS" isFollowed={false} stateUnknown={false} />);
        expect(screen.getByRole('button')).not.toHaveAttribute('aria-label');
        rerender(<FollowButton compact symbol="ASTS" isFollowed={false} stateUnknown />);
        expect(screen.getByRole('button')).not.toHaveAttribute('aria-label');
    });
});
