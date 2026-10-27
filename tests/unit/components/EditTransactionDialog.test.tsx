import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const updateTransaction = vi.fn();

vi.mock('@/lib/actions/portfolio.actions', () => ({
    updateTransaction: (...args: unknown[]) => updateTransaction(...args),
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: vi.fn(),
}));
vi.mock('next/navigation', () => ({
    useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import EditTransactionDialog from '@/components/portfolio/EditTransactionDialog';

const base = {
    _id: '7',
    symbol: 'SAN.MC',
    type: 'buy' as const,
    quantity: 10,
    price: 4,
    date: '2026-01-15',
    currency: 'EUR',
};

async function open(transaction: typeof base & { fees?: number }) {
    render(<EditTransactionDialog transaction={transaction} userId="user-1" />);
    fireEvent.click(screen.getByRole('button', { name: /Editar transacción/ }));
    return screen.getByRole('dialog');
}

describe('EditTransactionDialog comisiones', () => {
    beforeEach(() => updateTransaction.mockReset().mockResolvedValue(undefined));

    it('precarga la comisión registrada y la reenvía editada', async () => {
        const dialog = await open({ ...base, fees: 2.5 });
        const input = within(dialog).getByLabelText(/^Comisiones/) as HTMLInputElement;
        expect(input.value).toBe('2.5');
        fireEvent.change(input, { target: { value: '3' } });
        await act(async () => {
            fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Cambios' }).closest('form')!);
        });
        expect(updateTransaction).toHaveBeenCalledTimes(1);
        expect(updateTransaction.mock.calls[0][9]).toBe(3);
    });

    it('guardar sin tocar la comisión conserva la existente (no la pone a 0)', async () => {
        const dialog = await open({ ...base, fees: 2.5 });
        await act(async () => {
            fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Cambios' }).closest('form')!);
        });
        expect(updateTransaction.mock.calls[0][9]).toBe(2.5);
    });
});
