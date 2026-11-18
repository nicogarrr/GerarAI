import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import FollowButton from '@/components/screener/FollowButton';

// El componente importa @/lib/actions/watchlist.actions (NO un hipotético
// watchlist-toggle.actions) y @/lib/toast (NO @/components/ui/toast): mockes
// equivocados dejaban pasar los tests sin comprobar el cableado real.
const m = vi.hoisted(() => ({
    add: vi.fn(),
    remove: vi.fn(),
    success: vi.fn(),
    showError: vi.fn(),
}));
vi.mock('@/lib/actions/watchlist.actions', () => ({
    addToWatchlist: m.add,
    removeFromWatchlist: m.remove,
}));
vi.mock('sonner', () => ({ toast: { success: m.success, error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: m.showError }));

beforeEach(() => {
    vi.clearAllMocks();
    m.add.mockResolvedValue({ success: true });
    m.remove.mockResolvedValue({ success: true });
});

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

describe('FollowButton · cableado de la acción', () => {
    it('al seguir envía símbolo y empresa, cambia aria-pressed y avisa con el símbolo', async () => {
        render(<FollowButton symbol="asts" company="AST SpaceMobile" />);
        const button = screen.getByRole('button');
        expect(button).toHaveAttribute('aria-pressed', 'false');

        fireEvent.click(button);

        await waitFor(() => expect(m.add).toHaveBeenCalledWith('asts', 'AST SpaceMobile'));
        expect(m.remove).not.toHaveBeenCalled();
        await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'true'));
        expect(m.success).toHaveBeenCalledWith('asts añadido a la watchlist');
    });

    it('al dejar de seguir llama a removeFromWatchlist, vuelve a «no seguido» y avisa', async () => {
        render(<FollowButton symbol="ASTS" isFollowed />);
        const button = screen.getByRole('button');

        fireEvent.click(button);

        await waitFor(() => expect(m.remove).toHaveBeenCalledWith('ASTS'));
        expect(m.add).not.toHaveBeenCalled();
        await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'false'));
        expect(m.success).toHaveBeenCalledWith('ASTS eliminado de la watchlist');
    });

    it('un duplicado sincroniza el estado visible y muestra el motivo del backend', async () => {
        m.add.mockResolvedValueOnce({ success: false, code: 'duplicate', message: 'Ya sigues este ticker.' });
        render(<FollowButton symbol="ASTS" />);
        const button = screen.getByRole('button');

        fireEvent.click(button);

        await waitFor(() => expect(m.showError).toHaveBeenCalledWith(
            'Ya sigues este ticker.',
            expect.objectContaining({ duplicateMessage: 'Ya sigues este ticker.', onRetry: expect.any(Function) }),
        ));
        expect(button).toHaveAttribute('aria-pressed', 'true');
        expect(m.success).not.toHaveBeenCalled();
    });

    it('un fallo de red ofrece reintentar y el reintento completa el seguimiento', async () => {
        const error = new Error('Offline');
        m.add.mockRejectedValueOnce(error).mockResolvedValueOnce({ success: true });
        render(<FollowButton symbol="ASTS" />);
        const button = screen.getByRole('button');

        fireEvent.click(button);

        await waitFor(() => expect(m.showError).toHaveBeenCalledWith(error, { onRetry: expect.any(Function) }));
        expect(button).toHaveAttribute('aria-pressed', 'false');
        expect(button).toBeEnabled();
        expect(m.success).not.toHaveBeenCalled();

        await act(async () => { await m.showError.mock.calls[0][1].onRetry(); });

        expect(m.add).toHaveBeenCalledTimes(2);
        await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'true'));
        expect(m.success).toHaveBeenCalledOnce();
    });
});
