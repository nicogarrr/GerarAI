import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PagedInsiderCompanies } from '@/components/insider/PagedInsiderCompanies';
import type { InsiderOperationsCompany, InsiderOperationsSide } from '@/lib/actions/insider.actions';

// El paginador separa «Página x de y» en su propio span (NBSP/huérfanos 390px):
// hay que casar por textContent normalizado, no por texto plano.
const byTextContent = (text: string) => (_: string, el?: Element | null) =>
    (el?.textContent ?? '').replace(/\s+/g, ' ').trim() === text;

const none: InsiderOperationsSide = {
    trades: 0, shares: 0, value: 0, avg_price: null, shares_without_value: 0, rows_without_value: 0,
} as InsiderOperationsSide;

const company = (ticker: string): InsiderOperationsCompany => ({
    ticker,
    company: `${ticker} Inc`,
    origin: 'cartera',
    period: { from: '2026-01-05', to: '2026-10-01' },
    filings: 1,
    amended_filings: 0,
    totals: { buy: none, sell: none },
    insiders: [],
    excluded_codes: 0,
    excluded_derivative: 0,
    rows_without_date: 0,
} as unknown as InsiderOperationsCompany);

const companies = (n: number) => Array.from({ length: n }, (_, i) => company(`T${String(i + 1).padStart(2, '0')}`));

describe('PagedInsiderCompanies', () => {
    it('pagina la lista de empresas (10 por página, arriba y abajo)', () => {
        render(<PagedInsiderCompanies companies={companies(25)} />);
        expect(screen.getByText('T10')).toBeInTheDocument();
        expect(screen.queryByText('T11')).not.toBeInTheDocument();
        expect(screen.getAllByRole('navigation', { name: 'Paginación de empresas' })).toHaveLength(2);
        expect(screen.getAllByText(byTextContent('Página 1 de 3 · 25 empresas'))).toHaveLength(2);
        fireEvent.click(screen.getAllByRole('button', { name: 'Siguiente' })[0]);
        expect(screen.getByText('T11')).toBeInTheDocument();
        expect(screen.queryByText('T10')).not.toBeInTheDocument();
    });
    it('sin más de una página no pinta paginador', () => {
        render(<PagedInsiderCompanies companies={companies(3)} />);
        expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
        expect(screen.getByText('T03')).toBeInTheDocument();
    });
});
