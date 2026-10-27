import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const addTransaction = vi.fn();
const refresh = vi.fn();
const searchStocksWithStatus = vi.fn();
const toastSuccess = vi.fn();

vi.mock('@/lib/actions/portfolio.actions', () => ({
    addTransaction: (...args: unknown[]) => addTransaction(...args),
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: (q: string) => searchStocksWithStatus(q),
}));
vi.mock('next/navigation', () => ({
    useRouter: () => ({ refresh, push: vi.fn(), replace: vi.fn() }),
}));
vi.mock('sonner', () => ({
    toast: { success: (...args: unknown[]) => toastSuccess(...args), error: vi.fn() },
}));

import AddTransactionButton from '@/components/portfolio/AddTransactionButton';

async function flush(ms = 0) {
    await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
    });
}

function openDialog() {
    render(<AddTransactionButton userId="user-1" />);
    fireEvent.click(screen.getByRole('button', { name: /Añadir inversión/ }));
    return screen.getByRole('dialog');
}

async function pickTicker(dialog: HTMLElement, query: string, symbol: string) {
    const input = within(dialog).getByLabelText('Buscar Acción');
    act(() => input.focus());
    fireEvent.change(input, { target: { value: query } });
    await flush(300);
    await flush();
    fireEvent.click(screen.getByRole('option', { name: new RegExp(symbol.replace('.', '\\.')) }));
}

describe('AddTransactionButton (Nueva Inversión)', () => {
    beforeEach(() => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        addTransaction.mockReset().mockResolvedValue(undefined);
        searchStocksWithStatus.mockReset();
        refresh.mockReset();
        toastSuccess.mockReset();
    });
    afterEach(() => {
        vi.useRealTimers();
    });

    it('ningún submit falla en silencio: sin símbolo y con cantidad 0 se explica cada campo y no se llama al backend', async () => {
        const dialog = openDialog();
        fireEvent.change(within(dialog).getByLabelText('Cantidad'), { target: { value: '0' } });
        fireEvent.change(within(dialog).getByLabelText(/^Precio/), { target: { value: '10' } });
        // submit directo: simula un navegador que no aplica `required`/`min`.
        fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Inversión' }).closest('form')!);
        await flush();
        const alerts = within(dialog).getAllByRole('alert').map((a) => a.textContent);
        expect(alerts).toContain('Busca y selecciona una acción de la lista.');
        expect(alerts).toContain('Introduce una cantidad mayor que 0.');
        expect(alerts).not.toContain('Introduce un precio válido (0 o mayor).');
        expect(addTransaction).not.toHaveBeenCalled();
    });

    it('cantidad y precio aceptan decimales (no se limita a 2 decimales con step)', () => {
        const dialog = openDialog();
        for (const label of ['Cantidad', /^Precio/]) {
            const input = within(dialog).getByLabelText(label);
            expect(input).toHaveAttribute('step', 'any');
        }
    });

    it('un ticker de Madrid (SAN.MC) fija la divisa en EUR y la operación se envía con los valores tecleados', async () => {
        searchStocksWithStatus.mockResolvedValue({
            status: 'ok',
            stocks: [{ symbol: 'SAN.MC', name: 'Banco Santander SA', exchange: 'BME', type: 'Common Stock', isInWatchlist: false }],
        });
        const dialog = openDialog();
        await pickTicker(dialog, 'santander', 'SAN.MC');
        expect(within(dialog).getByText('Precio (EUR)')).toBeInTheDocument();

        fireEvent.change(within(dialog).getByLabelText('Cantidad'), { target: { value: '12.5' } });
        fireEvent.change(within(dialog).getByLabelText(/^Precio/), { target: { value: '4.1234' } });
        fireEvent.change(within(dialog).getByLabelText('Fecha'), { target: { value: '2026-01-15' } });
        fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Inversión' }).closest('form')!);
        await flush();

        expect(addTransaction).toHaveBeenCalledTimes(1);
        const [userId, symbol, type, quantity, price, date, notes, currency] = addTransaction.mock.calls[0];
        expect({ userId, symbol, type, quantity, price, notes, currency }).toEqual({
            userId: 'user-1',
            symbol: 'SAN.MC',
            type: 'buy',
            quantity: 12.5,
            price: 4.1234,
            notes: undefined,
            currency: 'EUR',
        });
        expect((date as Date).toISOString().slice(0, 10)).toBe('2026-01-15');
        expect(toastSuccess).toHaveBeenCalledWith('Transacción registrada');
        expect(refresh).toHaveBeenCalled();
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('una fecha futura se rechaza antes de llegar al backend', async () => {
        searchStocksWithStatus.mockResolvedValue({
            status: 'ok',
            stocks: [{ symbol: 'AAPL', name: 'Apple Inc', exchange: 'NASDAQ', type: 'Common Stock', isInWatchlist: false }],
        });
        const dialog = openDialog();
        await pickTicker(dialog, 'AAPL', 'AAPL');
        fireEvent.change(within(dialog).getByLabelText('Cantidad'), { target: { value: '1' } });
        fireEvent.change(within(dialog).getByLabelText(/^Precio/), { target: { value: '200' } });
        fireEvent.change(within(dialog).getByLabelText('Fecha'), { target: { value: '2999-01-01' } });
        fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Inversión' }).closest('form')!);
        await flush();
        expect(within(dialog).getByRole('alert')).toHaveTextContent('La fecha no puede ser futura.');
        expect(addTransaction).not.toHaveBeenCalled();
    });

    it('si el backend falla, el error se enseña y el diálogo sigue abierto con los datos', async () => {
        addTransaction.mockRejectedValueOnce(new Error('Backend caído'));
        searchStocksWithStatus.mockResolvedValue({
            status: 'ok',
            stocks: [{ symbol: 'AAPL', name: 'Apple Inc', exchange: 'NASDAQ', type: 'Common Stock', isInWatchlist: false }],
        });
        const dialog = openDialog();
        await pickTicker(dialog, 'AAPL', 'AAPL');
        fireEvent.change(within(dialog).getByLabelText('Cantidad'), { target: { value: '3' } });
        fireEvent.change(within(dialog).getByLabelText(/^Precio/), { target: { value: '150' } });
        fireEvent.change(within(dialog).getByLabelText('Fecha'), { target: { value: '2026-01-15' } });
        fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Inversión' }).closest('form')!);
        await flush();
        expect(addTransaction).toHaveBeenCalledTimes(1);
        expect(toastSuccess).not.toHaveBeenCalled();
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(within(dialog).getByLabelText('Cantidad')).toHaveValue(3);
        expect(within(dialog).getByRole('button', { name: 'Guardar Inversión' })).toBeEnabled();
    });
});
