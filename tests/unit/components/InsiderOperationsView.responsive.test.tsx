import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import InsiderOperationsView from '@/components/insider/InsiderOperationsView';
import type {
    InsiderOperationsCompany,
    InsiderOperationsResult,
    InsiderOperationsSide,
} from '@/lib/actions/insider.actions';

// La vista pintaba DOS árboles por insider: tarjetas móvil (`md:hidden`,
// role article) y tabla escritorio (`hidden md:block`). Contrato (decisión de
// diseño, 2026-11-14): UNA tabla responsiva por empresa (patrón PositionsTable
// /watchlist): un insider = una fila, con etiquetas móviles `md:hidden` por celda.
const none: InsiderOperationsSide = {
    trades: 0, shares: 0, value: 0, avg_price: null, shares_without_value: 0, rows_without_value: 0,
} as InsiderOperationsSide;
const side = (over: Partial<InsiderOperationsSide>): InsiderOperationsSide => ({
    ...none, trades: 2, shares: 1500, value: 150000, avg_price: 100, ...over,
}) as InsiderOperationsSide;

function company(over: Partial<InsiderOperationsCompany> = {}): InsiderOperationsCompany {
    return {
        ticker: 'ASTS',
        company: 'AST SpaceMobile',
        origin: 'cartera',
        period: { from: '2026-01-05', to: '2026-10-01' },
        filings: 3,
        amended_filings: 0,
        totals: { buy: none, sell: side({}) },
        insiders: [
            { insider: 'Doe John', role: 'Officer', officer_title: 'CFO', buy: none, sell: side({}), last_tx: '2026-10-01' },
            { insider: null, role: null, officer_title: null, buy: side({ trades: 1, rows_without_value: 1, avg_price: null }), sell: none, last_tx: null },
        ],
        excluded_codes: 0,
        excluded_derivative: 0,
        rows_without_date: 0,
        ...over,
    } as InsiderOperationsCompany;
}

const ok = (companies: InsiderOperationsCompany[]): InsiderOperationsResult =>
    ({ status: 'ok', days: 365, companies, companies_without_data: [] }) as InsiderOperationsResult;

describe('InsiderOperationsView responsiva (una fila por insider)', () => {
    it('un insider = una fila (sin árbol duplicado móvil/escritorio)', () => {
        render(<InsiderOperationsView result={ok([company()])} days={365} />);
        // No quedan tarjetas <article>.
        expect(screen.queryAllByRole('article')).toHaveLength(0);
        const region = screen.getByRole('region', { name: /Operaciones insider de ASTS/ });
        // Cabecera + 2 insiders = 3 filas (antes: 3 en la tabla + 2 artículos).
        expect(within(region).getAllByRole('row')).toHaveLength(3);
        // El nombre del insider aparece UNA vez (antes: tarjeta + tabla).
        expect(screen.getAllByText('Doe John')).toHaveLength(1);
    });

    it('la fila única conserva etiquetas móviles y declara el medio N/D', () => {
        render(<InsiderOperationsView result={ok([company()])} days={365} />);
        const region = screen.getByRole('region', { name: /Operaciones insider de ASTS/ });
        const rows = within(region).getAllByRole('row');
        // Etiquetas móviles por celda (visibles < md) en la fila de datos.
        expect(within(rows[1]).getByText('Ventas')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Compras')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Ops')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Última')).toBeInTheDocument();
        // La segunda fila (compra con filas sin importe) declara el medio N/D.
        expect(within(rows[2]).getByText(/precio medio N\/D/)).toBeInTheDocument();
        // Ventas vacías -> guion, una sola vez.
        expect(within(rows[2]).getAllByText('—').length).toBeGreaterThan(0);
    });
});
