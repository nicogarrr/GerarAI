import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const searchStocksWithStatus = vi.fn();

vi.mock('@/lib/actions/watchlist.actions', () => ({
    addToWatchlistCanonical: vi.fn(),
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: (q: string) => searchStocksWithStatus(q),
}));
vi.mock('next/navigation', () => ({
    useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));
vi.mock('sonner', () => ({
    toast: { success: vi.fn(), error: vi.fn() },
}));

import WatchlistAddButton from '@/components/watchlist/WatchlistAddButton';

async function flush(ms = 0) {
    await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
    });
}

async function openDialog(followed: string[]) {
    render(<WatchlistAddButton followedSymbols={followed} />);
    fireEvent.click(screen.getByRole('button', { name: /Añadir empresa/ }));
    // El contenido del diálogo llega en chunk diferido (next/dynamic): cada
    // vuelta cede al event loop sin romper los timers fake del debounce.
    for (let i = 0; i < 50 && !screen.queryByRole('dialog'); i++) await flush(100);
    return screen.getByRole('dialog');
}

beforeAll(async () => {
    // Calienta el chunk diferido del diálogo (next/dynamic) en tiempo real,
    // antes de que los tests activen los timers fake: la primera resolución
    // del import dinámico tarda tiempo real (transform del módulo en vitest).
    await import('@/components/watchlist/WatchlistAddDialog');
});

describe('WatchlistAddButton: ticker ya seguido', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        searchStocksWithStatus.mockResolvedValue([]);
    });
    afterEach(() => {
        vi.useRealTimers();
        vi.clearAllMocks();
    });

    it('dice «Ya sigues» en vez de dejar el diálogo en blanco (prueba real 27/10, AAPL)', async () => {
        const dialog = await openDialog(['AAPL', 'POOL']);
        const input = within(dialog).getByLabelText('Buscar acciones para añadir a la watchlist');
        fireEvent.change(input, { target: { value: 'aapl' } });
        await flush(300);
        expect(within(dialog).getByText(/Ya sigues «AAPL»/)).toBeInTheDocument();
        expect(within(dialog).queryByRole('button', { name: /por su símbolo/ })).not.toBeInTheDocument();
    });

    it('no muestra el aviso para un ticker que no sigues', async () => {
        const dialog = await openDialog(['AAPL']);
        const input = within(dialog).getByLabelText('Buscar acciones para añadir a la watchlist');
        fireEvent.change(input, { target: { value: 'KKR' } });
        await flush(300);
        expect(within(dialog).queryByText(/Ya sigues/)).not.toBeInTheDocument();
    });
});
