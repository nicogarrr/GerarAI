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
});
