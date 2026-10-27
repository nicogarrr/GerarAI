import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

function openDialog(followed: string[]) {
    render(<WatchlistAddButton followedSymbols={followed} />);
    fireEvent.click(screen.getByRole('button', { name: /Añadir empresa/ }));
    return screen.getByRole('dialog');
}

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
        const dialog = openDialog(['AAPL', 'POOL']);
        const input = within(dialog).getByLabelText('Buscar acciones para añadir a la watchlist');
        fireEvent.change(input, { target: { value: 'aapl' } });
        await flush(300);
        expect(within(dialog).getByText(/Ya sigues «AAPL»/)).toBeInTheDocument();
        expect(within(dialog).queryByRole('button', { name: /por su símbolo/ })).not.toBeInTheDocument();
    });

    it('no muestra el aviso para un ticker que no sigues', async () => {
        const dialog = openDialog(['AAPL']);
        const input = within(dialog).getByLabelText('Buscar acciones para añadir a la watchlist');
        fireEvent.change(input, { target: { value: 'KKR' } });
        await flush(300);
        expect(within(dialog).queryByText(/Ya sigues/)).not.toBeInTheDocument();
    });
});
