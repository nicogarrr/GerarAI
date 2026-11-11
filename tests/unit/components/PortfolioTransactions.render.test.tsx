import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

// Rendimiento de «Movimientos»: cada movimiento es un componente memoizado.
// Abrir/cancelar «Eliminar» no debe volver a pintar las filas (antes, con una
// página de 50 movimientos, cada clic repintaba las 50 filas con su diálogo de
// edición: 25–68 ms por clic en el banco frente a 3–10 ms).
const h = vi.hoisted(() => ({ edit: vi.fn(), logo: vi.fn(), refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: h.refresh }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteTransaction: vi.fn() }));
vi.mock('@/components/portfolio/EditTransactionDialog', () => ({ default: ({ transaction }: any) => { h.edit(transaction._id); return null; } }));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => null }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: ({ ticker }: { ticker: string }) => { h.logo(ticker); return null; } }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
import PortfolioTransactions from '@/components/portfolio/PortfolioTransactions';

const txs = Array.from({ length: 12 }, (_, i) => ({
    _id: `t${i}`, symbol: `S${String(i).padStart(2, '0')}`, type: i % 3 ? 'buy' : 'sell', quantity: 1 + i, price: 10 + i,
    date: '2026-01-15', currency: 'EUR',
})) as any[];

describe('Movimientos: render por fila', () => {
    it('abrir y cancelar «Eliminar» no repinta ningún movimiento', () => {
        render(<PortfolioTransactions transactions={txs} userId="u" page={{ total: 12, offset: 0 }} />);
        expect(h.edit).toHaveBeenCalledTimes(12);
        expect(h.logo).toHaveBeenCalledTimes(12);
        h.edit.mockClear();
        h.logo.mockClear();
        fireEvent.click(screen.getAllByRole('button', { name: 'Eliminar transacción' })[5]);
        expect(screen.getByRole('dialog')).toHaveTextContent('S05');
        fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
        expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument();
        expect(h.edit).not.toHaveBeenCalled();
        expect(h.logo).not.toHaveBeenCalled();
    });

    it('una página nueva de movimientos sí pinta sus filas', () => {
        const { rerender } = render(<PortfolioTransactions transactions={txs} userId="u" />);
        h.edit.mockClear();
        rerender(<PortfolioTransactions transactions={txs.map((tx) => ({ ...tx, price: tx.price + 1 }))} userId="u" />);
        expect(h.edit).toHaveBeenCalledTimes(12);
    });
});

describe('Movimientos: error de lectura vs vacío real (F1)', () => {
    it('fallo de lectura: aviso con botón Reintentar que refetchea la URL actual', () => {
        render(<PortfolioTransactions transactions={[]} userId="u" page={{ total: 0, offset: 50, filters: { ticker: 'AAPL', type: 'buy' } }} error="caído" />);
        expect(screen.getByRole('alert')).toHaveTextContent('No pudimos cargar tus movimientos');
        // Botón con router.refresh(): conserva pestaña, filtros y página (la URL
        // no cambia) y fuerza refetch real — un enlace a /portfolio volvía a
        // Resumen, y otro a la misma URL no refetchea desde caché.
        h.refresh.mockClear();
        fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
        expect(h.refresh).toHaveBeenCalledTimes(1);
        // El vacío normal afirmaría un ledger sin movimientos que no conocemos.
        expect(screen.queryByText('Aún no tienes movimientos')).toBeNull();
    });

    it('sin error: el vacío real sigue intacto', () => {
        render(<PortfolioTransactions transactions={[]} userId="u" page={{ total: 0, offset: 0 }} />);
        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText('Aún no tienes movimientos')).toBeInTheDocument();
    });
});
