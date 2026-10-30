import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteTransaction: vi.fn() }));
vi.mock('@/components/portfolio/EditTransactionDialog', () => ({ default: () => null }));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => null }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: () => null }));
import PortfolioTransactions from '@/components/portfolio/PortfolioTransactions';
import { parseTransactionFilters, transactionFiltersQuery, transactionsHref } from '@/lib/portfolio/transaction-filters';

const tx = { _id: '1', symbol: 'SAN.MC', type: 'buy' as const, quantity: 10, price: 4, date: '2025-03-01', currency: 'EUR' };

describe('Movimientos: filtros por ticker y tipo', () => {
    it('formulario GET con los filtros actuales y paginación que los conserva', () => {
        render(<PortfolioTransactions userId="u" transactions={[tx]} page={{ total: 120, offset: 50, filters: { ticker: 'SAN.MC', type: 'buy' } }} />);
        const form = screen.getByRole('search', { name: 'Filtrar movimientos' });
        expect(form).toHaveAttribute('method', 'get');
        expect(screen.getByLabelText('Ticker')).toHaveValue('SAN.MC');
        expect(screen.getByLabelText('Tipo')).toHaveValue('buy');
        expect(screen.getByRole('link', { name: 'Siguientes' })).toHaveAttribute('href', '/portfolio?tab=movimientos&ticker=SAN.MC&type=buy&transactionOffset=100');
        expect(screen.getByRole('link', { name: 'Anteriores' })).toHaveAttribute('href', '/portfolio?tab=movimientos&ticker=SAN.MC&type=buy&transactionOffset=0');
        expect(screen.getByRole('link', { name: 'Quitar filtros' })).toHaveAttribute('href', '/portfolio?tab=movimientos');
    });

    it('filtro sin resultados: no es el «primer uso», ofrece quitar filtros', () => {
        render(<PortfolioTransactions userId="u" transactions={[]} page={{ total: 0, offset: 0, filters: { ticker: 'ZZZ' } }} />);
        expect(screen.getByText('Ningún movimiento coincide con estos filtros')).toBeInTheDocument();
        expect(screen.queryByText('Aún no tienes movimientos')).not.toBeInTheDocument();
        expect(screen.getAllByRole('link', { name: 'Quitar filtros' }).length).toBeGreaterThan(0);
    });

    it('sin movimientos ni filtros: no hay formulario (primer uso)', () => {
        render(<PortfolioTransactions userId="u" transactions={[]} page={{ total: 0, offset: 0 }} />);
        expect(screen.queryByRole('search')).not.toBeInTheDocument();
        expect(screen.getByText('Aún no tienes movimientos')).toBeInTheDocument();
    });

    it('la URL se valida antes de llegar al backend', () => {
        expect(parseTransactionFilters({ ticker: ' san.mc ', type: 'sell' })).toEqual({ ticker: 'SAN.MC', type: 'sell' });
        expect(parseTransactionFilters({ ticker: 'a b;drop', type: 'dividend' })).toEqual({});
        expect(transactionFiltersQuery({ ticker: 'AAPL', type: 'sell' })).toBe('&ticker=AAPL&action=sell');
        expect(transactionFiltersQuery({})).toBe('');
        expect(transactionsHref({})).toBe('/portfolio?tab=movimientos');
    });
});
