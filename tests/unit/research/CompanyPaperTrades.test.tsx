import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { COMPANY_PAPER_LIMIT, CompanyPaperTrades } from '@/components/research/CompanyPaperTrades';
import type { PaperTradeView } from '@/lib/actions/paper-trading.actions';

const trade = (over: Partial<PaperTradeView> = {}): PaperTradeView => ({
    id: 1, ticker: 'TEST', direction: 'long', horizon: 'short', thesis: 'Tesis sintética', conviction: '0.5',
    proposed_entry: '100', stop: '90', target: '120', inference_basis: 'Fixture local', status: 'open', currency: 'USD',
    created_at: '2026-01-31T10:00:00Z', entry_price: '101', exit_price: null, mark_price: '110', mark_at: null,
    entry_at: null, exit_at: null, realized_pnl: null, unrealized_pnl: '9', unrealized_pnl_net: '7.5', close_reason: null,
    thesis_version_id: 3, thesis_anchor: { id: 3, version: 1, created_at: null, latest_version: 2, superseded: true }, ...over,
});

// Panel consulta el ancho del viewport; jsdom no trae matchMedia.
beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })); });
afterEach(() => vi.unstubAllGlobals());

describe('Company paper trades next to the decision journal', () => {
    it('lists only this company with gross and net results and the thesis it evaluated', () => {
        render(<CompanyPaperTrades ticker="test" state={{ trades: [trade(), trade({ id: 2, ticker: 'OTHER' })] }} />);
        const list = screen.getByRole('list', { name: 'Operaciones simuladas de test' });
        const items = within(list).getAllByRole('listitem');
        expect(items).toHaveLength(1);
        expect(items[0]).toHaveTextContent('Largo · operación a 30 días');
        expect(items[0]).toHaveTextContent('Abierta · creada el 31/1/2026');
        expect(items[0]).toHaveTextContent('Resultado abierto bruto +9 USD · neto +7,5 USD');
        expect(within(items[0]).getByText(/La tesis ha cambiado desde entonces/)).toBeVisible();
        expect(screen.getByRole('link', { name: /Ver el detalle/ })).toHaveAttribute('href', '/propicks?tab=paper');
    });
    it('labels pending, closed and unmarked trades without inventing results', () => {
        render(<CompanyPaperTrades ticker="TEST" state={{ trades: [
            trade({ id: 1, status: 'pending', unrealized_pnl: null }),
            trade({ id: 2, status: 'closed', realized_pnl: '-4', realized_pnl_net: null }),
            trade({ id: 3, unrealized_pnl: null, unrealized_pnl_net: null }),
        ] }} />);
        expect(screen.getByText(/Sin ejecutar/)).toBeVisible();
        expect(screen.getByText('Resultado bruto -4 USD · neto N/D')).toBeVisible();
        expect(screen.getByText(/Sin precio reciente/)).toBeVisible();
        expect(screen.queryByText(/NaN|undefined/)).not.toBeInTheDocument();
    });
    it('caps the list and says how many exist', () => {
        const trades = Array.from({ length: COMPANY_PAPER_LIMIT + 2 }, (_, i) => trade({ id: i + 1 }));
        render(<CompanyPaperTrades ticker="TEST" state={{ trades }} />);
        expect(screen.getAllByRole('listitem')).toHaveLength(COMPANY_PAPER_LIMIT);
        expect(screen.getByText(`Se muestran ${COMPANY_PAPER_LIMIT} de ${COMPANY_PAPER_LIMIT + 2}.`, { exact: false })).toBeVisible();
    });
    it('distinguishes an empty book from a failed load', () => {
        const { unmount } = render(<CompanyPaperTrades ticker="TEST" state={{ trades: [trade({ ticker: 'OTHER' })] }} />);
        expect(screen.getByText('Sin operaciones simuladas para esta empresa.')).toBeVisible();
        expect(screen.getByRole('link', { name: 'Ir a paper trading' })).toHaveAttribute('href', '/propicks?tab=paper');
        unmount();
        render(<CompanyPaperTrades ticker="TEST" state={{ trades: [], error: 'No se pudieron cargar las operaciones simuladas.' }} />);
        expect(screen.getByRole('status')).toHaveTextContent('No significa que no existan.');
        expect(screen.queryByText('Sin operaciones simuladas para esta empresa.')).not.toBeInTheDocument();
    });
});
