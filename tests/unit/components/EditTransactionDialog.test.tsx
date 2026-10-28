import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

describe('EditTransactionDialog foco al abrir', () => {
    it('no autoenfoca Símbolo al abrir: el desplegable de sugerencias tapaba Moneda/Tipo/Cantidad/Precio', async () => {
        await open({ ...base });
        await waitFor(() => {
            expect(document.activeElement?.id).not.toBe('symbol');
        });
    });
});

describe('EditTransactionDialog comisiones', () => {
    beforeEach(() => updateTransaction.mockReset().mockResolvedValue(undefined));

    it('precarga la comisión registrada y la reenvía editada', async () => {
        const dialog = await open({ ...base, fees: 2.5 });
        const input = within(dialog).getByLabelText(/^Comisiones/) as HTMLInputElement;
        expect(input.value).toBe('2,5');
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

    it('precarga cantidad/precio fraccionados en gramática es-ES y el guardar sin tocar conserva el valor', async () => {
        const dialog = await open({ ...base, quantity: 6.0572, price: 150.5 });
        expect((within(dialog).getByLabelText('Cantidad') as HTMLInputElement).value).toBe('6,0572');
        expect((within(dialog).getByLabelText(/^Precio/) as HTMLInputElement).value).toBe('150,5');
        await act(async () => {
            fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Cambios' }).closest('form')!);
        });
        expect(updateTransaction).toHaveBeenCalledTimes(1);
        expect(updateTransaction.mock.calls[0][4]).toBeCloseTo(6.0572, 10);
        expect(updateTransaction.mock.calls[0][5]).toBeCloseTo(150.5, 10);
    });

    it('fila sin dato de comisión: el campo va vacío y guardar sin tocarlo OMITE fees (no borra la registrada)', async () => {
        const dialog = await open(base);
        const input = within(dialog).getByLabelText(/^Comisiones/) as HTMLInputElement;
        expect(input.value).toBe('');
        await act(async () => {
            fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Cambios' }).closest('form')!);
        });
        expect(updateTransaction).toHaveBeenCalledTimes(1);
        expect(updateTransaction.mock.calls[0]).toHaveLength(10);
        expect(updateTransaction.mock.calls[0][9]).toBeUndefined();
    });

    it('fila sin dato de comisión: si el usuario teclea una, se envía', async () => {
        const dialog = await open(base);
        fireEvent.change(within(dialog).getByLabelText(/^Comisiones/), { target: { value: '4' } });
        await act(async () => {
            fireEvent.submit(within(dialog).getByRole('button', { name: 'Guardar Cambios' }).closest('form')!);
        });
        expect(updateTransaction.mock.calls[0][9]).toBe(4);
    });
});
