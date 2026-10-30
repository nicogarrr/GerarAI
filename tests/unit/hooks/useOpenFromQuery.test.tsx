import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DialogContent, DialogTitle } from '@/components/ui/dialog';
import { consumeOpenParam } from '@/hooks/useOpenFromQuery';
import { addTransactionHref } from '@/lib/portfolio/add-dialog-link';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }) }));
// Contenido mínimo con el DialogContent real: solo se ve si el diálogo está abierto.
vi.mock('@/components/portfolio/AddTransactionDialog', () => ({
    default: () => <DialogContent><DialogTitle>Nueva Inversión</DialogTitle></DialogContent>,
}));
vi.mock('@/components/watchlist/WatchlistAddDialog', () => ({
    default: () => <DialogContent><DialogTitle>Añadir a la watchlist</DialogTitle></DialogContent>,
}));
import AddTransactionButton from '@/components/portfolio/AddTransactionButton';
import WatchlistAddButton from '@/components/watchlist/WatchlistAddButton';

function goTo(url: string) {
    window.history.replaceState(null, '', url);
}

afterEach(() => goTo('/'));

describe('enlaces «…?anadir=1» de Primeros pasos', () => {
    it('consumeOpenParam lo lee una vez y lo quita de la URL sin tocar el resto', () => {
        goTo('/portfolio?tab=posiciones&anadir=1#lista');
        expect(consumeOpenParam()).toEqual({ symbol: null });
        expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe('/portfolio?tab=posiciones#lista');
        expect(consumeOpenParam()).toBeNull();
        goTo('/portfolio?anadir=0');
        expect(consumeOpenParam()).toBeNull();
    });

    it('consumeOpenParam devuelve el símbolo y quita también «simbolo» de la URL', () => {
        goTo(addTransactionHref('BRK.B'));
        expect(window.location.search).toBe('?anadir=1&simbolo=BRK.B');
        expect(consumeOpenParam()).toEqual({ symbol: 'BRK.B' });
        expect(window.location.search).toBe('');
    });

    it('/portfolio?anadir=1 abre «Nueva Inversión» una sola vez aunque haya varios botones', async () => {
        goTo('/portfolio?anadir=1');
        render(<><AddTransactionButton userId="u" /><AddTransactionButton userId="u" /></>);
        await waitFor(() => expect(screen.getAllByRole('dialog')).toHaveLength(1));
        expect(screen.getByText('Nueva Inversión')).toBeInTheDocument();
        expect(window.location.search).toBe('');
    });

    it('/watchlist?anadir=1 abre el alta de la watchlist; sin el parámetro no se abre nada', async () => {
        goTo('/watchlist?anadir=1');
        const { unmount } = render(<WatchlistAddButton followedSymbols={[]} />);
        expect(await screen.findByRole('dialog')).toBeInTheDocument();
        unmount();
        goTo('/watchlist');
        render(<WatchlistAddButton followedSymbols={[]} />);
        await new Promise((r) => setTimeout(r, 50));
        expect(screen.queryByRole('dialog')).toBeNull();
    });
});
