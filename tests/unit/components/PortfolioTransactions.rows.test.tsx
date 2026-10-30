import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const h = vi.hoisted(() => ({ del: vi.fn(), refresh: vi.fn(), success: vi.fn(), error: vi.fn(), showError: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: h.refresh }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteTransaction: h.del }));
vi.mock('@/components/portfolio/EditTransactionDialog', () => ({ default: ({ transaction }: any) => <span>edit-{transaction._id}</span> }));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => <span>import-ibkr</span> }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => <span>add-tx</span> }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: () => null }));
vi.mock('sonner', () => ({ toast: { success: h.success, error: h.error } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: h.showError }));
import PortfolioTransactions from '@/components/portfolio/PortfolioTransactions';

const tx = (over: Record<string, unknown> = {}): any => ({ _id: '1', symbol: 'AAPL', type: 'buy', quantity: 3, price: 10.5, date: '2026-01-15', currency: 'EUR', ...over });

beforeEach(() => vi.clearAllMocks());

describe('PortfolioTransactions filas', () => {
    it('sin ningun movimiento: primer uso con alta manual e importador, sin paginador «0 de 0» ni nota de nocional', () => {
        render(<PortfolioTransactions transactions={[]} userId="u" page={{ total: 0, offset: 0 }} />);
        expect(screen.getByText('Aún no tienes movimientos')).toBeInTheDocument();
        expect(screen.getByText('add-tx')).toBeInTheDocument();
        expect(screen.getByText('import-ibkr')).toBeInTheDocument();
        expect(screen.queryByText('0 de 0')).not.toBeInTheDocument();
        expect(screen.queryByText('Sin movimientos en esta página')).not.toBeInTheDocument();
        expect(screen.queryByText(/nocional/)).not.toBeInTheDocument();
    });

    it('importe = cantidad x precio rotulado bruto, con la divisa del movimiento', () => {
        render(<PortfolioTransactions transactions={[tx({ quantity: 3, price: 10.5 })]} userId="u" />);
        const gross = screen.getByText('bruto').parentElement!;
        expect(gross.textContent).toMatch(/31,50\s?€/);
        expect(screen.getByText(/nocional del movimiento/)).toBeInTheDocument();
        expect(screen.getByText(/3 acc @/).textContent).toMatch(/10,50\s?€/);
    });

    it('divisa ausente o invalida: importe N/D, nunca USD por defecto', () => {
        render(<PortfolioTransactions transactions={[tx({ currency: undefined }), tx({ _id: '2', currency: 'XXXXX' })]} userId="u" />);
        const gross = screen.getAllByText('bruto').map((e) => e.parentElement!.textContent);
        expect(gross.every((t) => t!.startsWith('N/D'))).toBe(true);
        expect(document.body.textContent).not.toContain('$');
        expect(screen.getAllByText(/acc @ N\/D/)).toHaveLength(2);
    });

    it('compra vs venta: etiqueta y signo', () => {
        render(<PortfolioTransactions transactions={[tx(), tx({ _id: '2', type: 'sell', symbol: 'MSFT' })]} userId="u" />);
        expect(screen.getByText('Compra')).toBeInTheDocument();
        expect(screen.getByText('Venta')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'MSFT' })).toHaveAttribute('href', '/research/MSFT');
    });

    it('compra a precio 0: insignia «Coste 0 (regalo / spin-off): revisar», solo en compras a 0', () => {
        render(<PortfolioTransactions transactions={[
            tx({ _id: 'gift', symbol: 'GIFT', price: 0, quantity: 5 }),
            tx({ _id: 'buy', symbol: 'AAPL', price: 10 }),
            tx({ _id: 'sell0', symbol: 'SELL0', type: 'sell', price: 0 }),
        ]} userId="u" />);
        const badges = screen.getAllByText('Coste 0 (regalo / spin-off): revisar');
        expect(badges).toHaveLength(1);
        expect(badges[0].closest('.group')!.textContent).toContain('GIFT');
    });

    it('cantidad fraccionaria hasta 4 decimales', () => {
        render(<PortfolioTransactions transactions={[tx({ quantity: 0.12345678 })]} userId="u" />);
        expect(screen.getByText(/0,1235 acc/)).toBeInTheDocument();
    });

    it('pagina vacia pero con total: 0 de N y enlace a la primera pagina', () => {
        render(<PortfolioTransactions transactions={[]} userId="u" page={{ total: 7, offset: 100 }} />);
        expect(screen.getByText('0 de 7')).toBeInTheDocument();
        expect(screen.getByText('Sin movimientos en esta página')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Ir a la primera página' })).toHaveAttribute('href', '/portfolio?tab=movimientos');
        expect(screen.queryByText('Aún no tienes movimientos')).not.toBeInTheDocument();
    });

    it('offset nunca negativo en el enlace Anteriores', () => {
        render(<PortfolioTransactions transactions={[tx()]} userId="u" page={{ total: 100, offset: 20 }} />);
        expect(screen.getByRole('link', { name: 'Anteriores' }).getAttribute('href')).toContain('transactionOffset=0');
    });
});

describe('PortfolioTransactions eliminar', () => {
    const del = () => fireEvent.click(screen.getByRole('button', { name: 'Eliminar transacción' }));

    it('el dialogo nombra el movimiento exacto y avisa de que no se puede deshacer', () => {
        render(<PortfolioTransactions transactions={[tx({ _id: 'a', symbol: 'KO' }), tx({ _id: 'b', symbol: 'MSFT', type: 'sell', quantity: 2.5, price: 400, currency: 'USD', date: '2026-02-03' })]} userId="u" />);
        fireEvent.click(screen.getAllByRole('button', { name: 'Eliminar transacción' })[1]);
        const text = screen.getByRole('dialog').textContent!;
        expect(text).toMatch(/¿Eliminar la venta de 2,5 MSFT del .*2026 a 400,00\s?US\$\?/);
        expect(text).toContain('No se puede deshacer');
        expect(text).not.toContain('KO');
    });

    it('cancelar no borra', () => {
        render(<PortfolioTransactions transactions={[tx()]} userId="u" />);
        del();
        fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
        expect(h.del).not.toHaveBeenCalled();
    });

    it('confirmar borra la transaccion correcta del usuario y refresca', async () => {
        h.del.mockResolvedValue(undefined);
        render(<PortfolioTransactions transactions={[tx({ _id: '77' })]} userId="u9" />);
        del();
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('Transacción eliminada'));
        expect(h.del).toHaveBeenCalledWith('u9', '77');
        expect(h.refresh).toHaveBeenCalled();
    });

    it('rechazo del ledger (una venta posterior se quedaría sin acciones): motivo en español, sin éxito ni refresh', async () => {
        h.del.mockResolvedValue({ success: false, error: 'No se puede borrar: una venta posterior se quedaría sin acciones.' });
        render(<PortfolioTransactions transactions={[tx()]} userId="u" />);
        del();
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        await waitFor(() => expect(h.error).toHaveBeenCalledWith('No se puede borrar: una venta posterior se quedaría sin acciones.'));
        expect(h.success).not.toHaveBeenCalled();
        expect(h.refresh).not.toHaveBeenCalled();
    });

    it('fallo: error con reintento, sin exito ni refresh', async () => {
        h.del.mockRejectedValue(new Error('x'));
        render(<PortfolioTransactions transactions={[tx()]} userId="u" />);
        del();
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(h.showError.mock.calls[0][1]).toHaveProperty('onRetry');
        expect(h.success).not.toHaveBeenCalled();
        expect(h.refresh).not.toHaveBeenCalled();
        h.del.mockResolvedValue(undefined);
        h.showError.mock.calls[0][1].onRetry();
        await waitFor(() => expect(h.success).toHaveBeenCalled());
    });
});

describe('PortfolioTransactions: objetivo táctil', () => {
    it('el enlace del ticker mide 44 px en móvil', () => {
        render(<PortfolioTransactions transactions={[tx()]} userId="u" />);
        expect(screen.getByRole('link', { name: 'AAPL' }).className).toMatch(/min-h-\[44px\]/);
    });
});
