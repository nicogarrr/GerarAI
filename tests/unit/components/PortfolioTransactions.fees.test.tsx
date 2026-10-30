import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteTransaction: vi.fn() }));
vi.mock('@/components/portfolio/EditTransactionDialog', () => ({ default: () => null }));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => null }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: () => null }));
import PortfolioTransactions from '@/components/portfolio/PortfolioTransactions';

const base = { type: 'buy' as const, quantity: 10, price: 150, date: '2025-03-01', currency: 'USD' };

describe('Movimientos: comisiones, notas y recuentos es-ES', () => {
    it('muestra la comisión guardada en la divisa del movimiento y la nota', () => {
        render(<PortfolioTransactions userId="u" transactions={[
            { ...base, _id: '1', symbol: 'AAPL', fees: 1.25, notes: 'Compra mensual DCA' },
        ]} />);
        expect(screen.getByText(/Comisión 1,25\sUS\$/)).toBeInTheDocument();
        expect(screen.getByText('Compra mensual DCA')).toBeInTheDocument();
    });

    it('sin comisión (0 o ausente) no pinta la línea', () => {
        render(<PortfolioTransactions userId="u" transactions={[
            { ...base, _id: '1', symbol: 'AAPL', fees: 0 },
            { ...base, _id: '2', symbol: 'MSFT' },
        ]} />);
        expect(screen.queryByText(/Comisión/)).not.toBeInTheDocument();
    });

    it('el recuento de páginas usa separador de miles', () => {
        render(<PortfolioTransactions userId="u" transactions={[{ ...base, _id: '1', symbol: 'AAPL' }]} page={{ total: 1500, offset: 1450 }} />);
        expect(screen.getByText('1451-1451 de 1500'.replace('1500', '1.500').replace('1451-1451', '1.451-1.451'))).toBeInTheDocument();
    });
});
