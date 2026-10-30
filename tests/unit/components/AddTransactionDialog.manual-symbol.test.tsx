import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const addTransaction = vi.fn();
vi.mock('@/lib/actions/portfolio.actions', () => ({ addTransaction: (...args: unknown[]) => addTransaction(...args) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
vi.mock('@/components/ui/dialog', () => ({
    DialogContent: ({ children }: { children: React.ReactNode }) => <div role="dialog">{children}</div>,
    DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
    DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}));
// Buscador sin resultados (proveedor caído o ticker no cubierto): solo texto.
vi.mock('@/components/search/TickerSearchInput', () => ({
    TickerSearchInput: ({ value, onValueChange }: { value: string; onValueChange: (v: string) => void }) => (
        <input aria-label="buscador" value={value} onChange={(e) => onValueChange(e.target.value)} />
    ),
}));
import AddTransactionDialog from '@/components/portfolio/AddTransactionDialog';

describe('Nueva inversión sin sugerencias del buscador', () => {
    it('permite usar el ticker escrito y registrar la operación', async () => {
        addTransaction.mockReset();
        const onClose = vi.fn();
        render(<AddTransactionDialog userId="u" onClose={onClose} />);
        fireEvent.change(screen.getByLabelText('buscador'), { target: { value: 'sap.de' } });
        fireEvent.click(screen.getByRole('button', { name: 'Usar «SAP.DE» como símbolo' }));
        // Fijado como símbolo, sin «- » colgando por falta de nombre, y con la
        // divisa de su bolsa (Xetra → EUR).
        expect(screen.queryByRole('button', { name: /como símbolo/ })).toBeNull();
        expect(screen.getByText(/Precio \(EUR\)/)).toBeInTheDocument();
        expect(screen.queryByText(/^- $/)).toBeNull();

        fireEvent.change(screen.getByLabelText('Cantidad'), { target: { value: '4' } });
        fireEvent.change(screen.getByLabelText('Precio (EUR)'), { target: { value: '180,50' } });
        fireEvent.submit(screen.getByLabelText('Cantidad').closest('form')!);
        await waitFor(() => expect(addTransaction).toHaveBeenCalledTimes(1));
        const [, symbol, type, quantity, price, , , currency] = addTransaction.mock.calls[0];
        expect([symbol, type, quantity, price, currency]).toEqual(['SAP.DE', 'buy', 4, 180.5, 'EUR']);
        expect(onClose).toHaveBeenCalled();
    });

    it('no ofrece usar como símbolo un texto que no tiene forma de ticker', () => {
        render(<AddTransactionDialog userId="u" onClose={() => {}} />);
        fireEvent.change(screen.getByLabelText('buscador'), { target: { value: 'Banco Santander' } });
        expect(screen.queryByRole('button', { name: /como símbolo/ })).toBeNull();
    });
});

describe('Nueva inversión con el símbolo ya elegido (enlace desde la ficha)', () => {
    it('llega con el símbolo fijado y la divisa de su bolsa', async () => {
        addTransaction.mockReset();
        render(<AddTransactionDialog userId="u" onClose={vi.fn()} initialSymbol="msft" />);
        expect(screen.getByLabelText('buscador')).toHaveValue('MSFT');
        expect(screen.getByText('MSFT')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /como símbolo/ })).toBeNull();
        expect(screen.getByText(/Precio \(USD\)/)).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('Cantidad'), { target: { value: '2' } });
        fireEvent.change(screen.getByLabelText('Precio (USD)'), { target: { value: '410' } });
        fireEvent.submit(screen.getByLabelText('Cantidad').closest('form')!);
        await waitFor(() => expect(addTransaction).toHaveBeenCalledTimes(1));
        expect(addTransaction.mock.calls[0][1]).toBe('MSFT');
    });

    it('un símbolo con forma inválida en la URL se ignora: formulario vacío', () => {
        render(<AddTransactionDialog userId="u" onClose={vi.fn()} initialSymbol="<script>" />);
        expect(screen.getByLabelText('buscador')).toHaveValue('');
        expect(screen.queryByText('<SCRIPT>')).toBeNull();
    });
});
