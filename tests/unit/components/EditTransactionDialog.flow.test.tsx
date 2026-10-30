import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ update: vi.fn(), refresh: vi.fn(), success: vi.fn(), error: vi.fn(), showError: vi.fn() }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ updateTransaction: h.update }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ searchStocksWithStatus: vi.fn().mockResolvedValue([]) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: h.refresh }) }));
vi.mock('sonner', () => ({ toast: { success: h.success, error: h.error } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: h.showError }));
import EditTransactionDialog from '@/components/portfolio/EditTransactionDialog';

const base = { _id: '7', symbol: 'SAN.MC', type: 'buy' as const, quantity: 10, price: 4, date: '2026-01-15T10:00:00Z', currency: 'EUR', notes: 'nota' };

function open(tx: any = base) {
    render(<EditTransactionDialog transaction={tx} userId="user-1" />);
    fireEvent.click(screen.getByRole('button', { name: /Editar transacción/ }));
    return within(screen.getByRole('dialog'));
}
const submit = async (d: ReturnType<typeof open>) => {
    await act(async () => { fireEvent.submit(d.getByRole('button', { name: 'Guardar cambios' }).closest('form')!); });
};

beforeEach(() => { vi.clearAllMocks(); h.update.mockResolvedValue(undefined); });

describe('EditTransactionDialog', () => {
    it('cancelar descarta lo tecleado: al reabrir se ven los datos guardados', () => {
        const d = open();
        fireEvent.change(d.getByLabelText('Cantidad'), { target: { value: '99' } });
        fireEvent.click(d.getByRole('button', { name: 'Cancelar' }));
        fireEvent.click(screen.getByRole('button', { name: /Editar transacción/ }));
        const again = within(screen.getByRole('dialog'));
        expect((again.getByLabelText('Cantidad') as HTMLInputElement).value).toBe('10');
        expect(h.update).not.toHaveBeenCalled();
    });

    it('divisa fuera de la lista corta (SEK): el selector la muestra y se conserva al guardar', async () => {
        const d = open({ ...base, symbol: 'VOLV-B.ST', currency: 'SEK' });
        expect(d.getByLabelText('Moneda de la operación').textContent).toContain('SEK');
        await submit(d);
        await waitFor(() => expect(h.update).toHaveBeenCalled());
        expect(h.update.mock.calls[0][8]).toBe('SEK');
    });

    it('precarga los datos y recorta la fecha a YYYY-MM-DD', () => {
        const d = open();
        expect((d.getByLabelText('Cantidad') as HTMLInputElement).value).toBe('10');
        expect((d.getByLabelText(/^Precio/) as HTMLInputElement).value).toBe('4');
        expect((d.getByLabelText('Fecha') as HTMLInputElement).value).toBe('2026-01-15');
        expect((d.getByLabelText(/^Notas/) as HTMLTextAreaElement).value).toBe('nota');
    });

    it('guardado correcto envia los argumentos en orden, cierra y refresca', async () => {
        const d = open();
        fireEvent.change(d.getByLabelText('Cantidad'), { target: { value: '12.5' } });
        fireEvent.change(d.getByLabelText(/^Precio/), { target: { value: '4.25' } });
        await submit(d);
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('Transacción actualizada'));
        const a = h.update.mock.calls[0];
        expect(a.slice(0, 3)).toEqual(['user-1', '7', 'SAN.MC']);
        expect(a[3]).toBe('buy');
        expect(a[4]).toBe(12.5);
        expect(a[5]).toBe(4.25);
        expect(a[6]).toEqual(new Date('2026-01-15'));
        expect(a[7]).toBe('nota');
        expect(a[8]).toBe('EUR');
        expect(a[9]).toBeUndefined();
        expect(h.refresh).toHaveBeenCalled();
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    });

    it('notas vacias se envian como undefined, no como cadena vacia', async () => {
        const d = open({ ...base, notes: undefined });
        await submit(d);
        await waitFor(() => expect(h.update).toHaveBeenCalled());
        expect(h.update.mock.calls[0][7]).toBeUndefined();
    });

    it('moneda por defecto USD si la fila no la trae', async () => {
        const d = open({ ...base, currency: undefined });
        await submit(d);
        await waitFor(() => expect(h.update).toHaveBeenCalled());
        expect(h.update.mock.calls[0][8]).toBe('USD');
    });

    it('validacion: cantidad 0, precio negativo y fecha futura bloquean el envio con mensajes por campo', async () => {
        const d = open();
        fireEvent.change(d.getByLabelText('Cantidad'), { target: { value: '0' } });
        fireEvent.change(d.getByLabelText(/^Precio/), { target: { value: '-1' } });
        fireEvent.change(d.getByLabelText('Fecha'), { target: { value: '2999-01-01' } });
        await submit(d);
        const alerts = d.getAllByRole('alert').map((a) => a.textContent);
        expect(alerts).toEqual(expect.arrayContaining([
            'Introduce una cantidad mayor que 0.', 'Introduce un precio válido (0 o mayor).',
            'La fecha no puede ser futura.',
        ]));
        expect(h.update).not.toHaveBeenCalled();
    });

    it('simbolo vacio bloquea el envio', async () => {
        const d = open();
        fireEvent.change(d.getByLabelText('Símbolo'), { target: { value: '' } });
        await submit(d);
        expect(d.getByText('Busca y selecciona una acción de la lista.')).toBeInTheDocument();
        expect(h.update).not.toHaveBeenCalled();
    });

    it('al escribir el simbolo se pasa a mayusculas', async () => {
        const d = open();
        fireEvent.change(d.getByLabelText('Símbolo'), { target: { value: 'kkr' } });
        await submit(d);
        await waitFor(() => expect(h.update).toHaveBeenCalled());
        expect(h.update.mock.calls[0][2]).toBe('KKR');
    });

    it('error del servidor: toast de error, el dialogo sigue abierto y sin exito', async () => {
        h.update.mockRejectedValue(new Error('boom'));
        const d = open();
        await submit(d);
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(h.success).not.toHaveBeenCalled();
        expect(h.refresh).not.toHaveBeenCalled();
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(d.getByRole('button', { name: 'Guardar cambios' })).not.toBeDisabled();
    });

    it('un redirect de Next se relanza y no se muestra como error', async () => {
        const redirect = Object.assign(new Error('NEXT_REDIRECT'), { digest: 'NEXT_REDIRECT;replace;/sign-in' });
        h.update.mockRejectedValue(redirect);
        const d = open();
        const errors: unknown[] = [];
        const onUnhandled = (e: unknown) => errors.push(e);
        process.on('unhandledRejection', onUnhandled);
        await submit(d);
        await new Promise((r) => setTimeout(r, 20));
        process.off('unhandledRejection', onUnhandled);
        expect(h.showError).not.toHaveBeenCalled();
    });
    it('comision: sin dato en la fila y campo vacio se omite', async () => {
        const d = open();
        await submit(d);
        expect(h.update.mock.calls[0][9]).toBeUndefined();
    });

    it('comision escrita se envia como numero', async () => {
        const d = open();
        fireEvent.change(d.getByLabelText(/^Comisiones/), { target: { value: '1.5' } });
        await submit(d);
        expect(h.update.mock.calls[0][9]).toBe(1.5);
    });

    it('comision registrada en 0 se conserva como 0 (no se omite)', async () => {
        const d = open({ ...base, fees: 0 });
        await submit(d);
        expect(h.update.mock.calls[0][9]).toBe(0);
    });

    it('editar notas se envia', async () => {
        const d = open();
        fireEvent.change(d.getByLabelText(/^Notas/), { target: { value: 'otra' } });
        await submit(d);
        expect(h.update.mock.calls[0][7]).toBe('otra');
    });

    it('Cancelar cierra el dialogo sin guardar', async () => {
        const d = open();
        fireEvent.click(d.getByRole('button', { name: 'Cancelar' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(h.update).not.toHaveBeenCalled();
    });
});

describe('EditTransactionDialog: rechazo del ledger', () => {
    it('vender de más: el diálogo sigue abierto con el motivo en español y no refresca', async () => {
        h.update.mockResolvedValue({ success: false, error: 'No puedes vender más acciones de las que tienes en cartera.' });
        const d = open({ ...base, type: 'sell' });
        await submit(d);
        await waitFor(() => expect(h.error).toHaveBeenCalledWith('No puedes vender más acciones de las que tienes en cartera.'));
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(h.success).not.toHaveBeenCalled();
        expect(h.refresh).not.toHaveBeenCalled();
    });
});
