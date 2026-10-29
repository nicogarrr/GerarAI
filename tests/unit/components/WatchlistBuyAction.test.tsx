import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const addTransaction = vi.fn();
const refresh = vi.fn();
const toastSuccess = vi.fn();

vi.mock('@/lib/actions/portfolio.actions', () => ({
    addTransaction: (...args: unknown[]) => addTransaction(...args),
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: vi.fn().mockResolvedValue({ status: 'ok', stocks: [] }),
}));
vi.mock('next/navigation', () => ({
    useRouter: () => ({ refresh, push: vi.fn(), replace: vi.fn() }),
}));
vi.mock('sonner', () => ({
    toast: { success: (...args: unknown[]) => toastSuccess(...args), error: vi.fn() },
}));

import WatchlistBuyAction from '@/components/watchlist/WatchlistBuyAction';

async function flush(ms = 0) {
    await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
    });
}

async function openDialog() {
    render(<WatchlistBuyAction userId="user-1" symbol="SAN.MC" companyName="Banco Santander SA" variant="menu-item" />);
    fireEvent.click(screen.getByRole('button', { name: 'Registrar compra' }));
    for (let i = 0; i < 50 && !screen.queryByRole('dialog'); i++) await flush(100);
    return screen.getByRole('dialog');
}

describe('WatchlistBuyAction', () => {
    beforeAll(async () => {
        // Calienta el chunk diferido (next/dynamic) en tiempo real, antes de
        // los timers fake: la primera resolución del import tarda tiempo real.
        await import('@/components/portfolio/AddTransactionDialog');
    });
    beforeEach(() => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        vi.clearAllMocks();
        addTransaction.mockResolvedValue({ success: true });
    });
    afterEach(() => vi.useRealTimers());

    it('abre el flujo de alta con la acción de la watchlist ya seleccionada', async () => {
        const dialog = await openDialog();
        // La ficha ya muestra empresa y ticker; no hace falta buscarla.
        expect(within(dialog).getByText('SAN.MC')).toBeInTheDocument();
        expect(within(dialog).getByText(/Banco Santander SA/)).toBeInTheDocument();
    });

    it('registra la compra con el símbolo preseleccionado', async () => {
        const dialog = await openDialog();
        fireEvent.change(within(dialog).getByLabelText('Cantidad'), { target: { value: '10' } });
        fireEvent.change(within(dialog).getByLabelText(/^Precio/), { target: { value: '4' } });
        fireEvent.change(within(dialog).getByLabelText('Fecha'), { target: { value: '2026-01-15' } });
        fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Inversión' }).closest('form')!);
        await flush();

        expect(addTransaction).toHaveBeenCalledOnce();
        const [userId, symbol, type] = addTransaction.mock.calls[0];
        expect({ userId, symbol, type }).toEqual({ userId: 'user-1', symbol: 'SAN.MC', type: 'buy' });
    });
});
