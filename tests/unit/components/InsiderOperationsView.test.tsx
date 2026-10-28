import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import InsiderOperationsView from '@/components/insider/InsiderOperationsView';
import type {
    InsiderOperationsCompany,
    InsiderOperationsResult,
    InsiderOperationsSide,
} from '@/lib/actions/insider.actions';

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
            {
                insider: 'Doe John', role: 'Officer', officer_title: 'CFO',
                buy: none, sell: side({}), last_tx: '2026-10-01',
            },
            {
                insider: null, role: null, officer_title: null,
                buy: side({ trades: 1, rows_without_value: 1, avg_price: null }), sell: none, last_tx: null,
            },
        ],
        excluded_codes: 0,
        excluded_derivative: 0,
        rows_without_date: 0,
        ...over,
    } as InsiderOperationsCompany;
}

const ok = (companies: InsiderOperationsCompany[], extra: Partial<InsiderOperationsResult> = {}): InsiderOperationsResult =>
    ({ status: 'ok', days: 365, companies, companies_without_data: [], ...extra }) as InsiderOperationsResult;

describe('InsiderOperationsView', () => {
    it.each([null, { status: 'unavailable', days: 365, companies: [], companies_without_data: [] } as InsiderOperationsResult])(
        'sin agregado muestra aviso honesto (%#)',
        (result) => {
            render(<InsiderOperationsView result={result} days={365} />);
            expect(screen.getByText(/No se pudo leer el agregado/)).toBeInTheDocument();
        },
    );

    it('sin empresas explica el vacío con los días', () => {
        render(<InsiderOperationsView result={ok([])} days={90} />);
        expect(screen.getByText(/Sin operaciones insider persistidas en los últimos 90 días/)).toBeInTheDocument();
    });

    it('lista empresas con origen, periodo, totales y enlace a insider', () => {
        render(<InsiderOperationsView result={ok([company(), company({ ticker: 'META', origin: 'watchlist', filings: 1 })], { companies_without_data: ['AAA', 'BBB'] })} days={365} />);
        expect(screen.getAllByRole('link', { name: 'ASTS' })[0]).toHaveAttribute('href', '/insider?ticker=ASTS');
        expect(screen.getByText('Cartera')).toBeInTheDocument();
        expect(screen.getByText('Watchlist')).toBeInTheDocument();
        expect(screen.getAllByText(/05\/01\/2026|5 ene 2026|05-01-2026|2026/).length).toBeGreaterThan(0);
        expect(screen.getByText(/1\s+filing\b/)).toBeInTheDocument();
        expect(screen.getByText(/3\s+filings/)).toBeInTheDocument();
        expect(screen.getByText(/AAA, BBB/)).toBeInTheDocument();
        expect(screen.getByRole('region', { name: /Operaciones insider de ASTS/ })).toBeInTheDocument();
    });

    it('marca como mínimo y N/D cuando hay filas sin importe', () => {
        const c = company({
            totals: { buy: side({ rows_without_value: 1 }), sell: side({}) },
        });
        render(<InsiderOperationsView result={ok([c])} days={365} />);
        expect(screen.getByText(/total comprado ≥/)).toBeInTheDocument();
        expect(screen.getAllByText(/precio medio N\/D/).length).toBeGreaterThan(0);
        expect(screen.getByText(/1 sin importe/)).toBeInTheDocument();
    });

    it('declara periodo sin fechas y avisos de exclusiones y enmiendas', () => {
        const c = company({
            period: { from: null, to: null },
            excluded_codes: 4,
            excluded_derivative: 2,
            rows_without_date: 1,
            amended_filings: 1,
        });
        render(<InsiderOperationsView result={ok([c])} days={365} />);
        expect(screen.getByText('Periodo sin fechas')).toBeInTheDocument();
        expect(screen.getByText(/4 operaciones de otros códigos/)).toBeInTheDocument();
        expect(screen.getByText(/2 derivadas excluidas/)).toBeInTheDocument();
        expect(screen.getByText(/1 sin fecha/)).toBeInTheDocument();
        expect(screen.getByText(/1 enmienda\(s\) 4\/A/)).toBeInTheDocument();
    });

    it('sin avisos no pinta el pie de exclusiones', () => {
        render(<InsiderOperationsView result={ok([company()])} days={365} />);
        expect(screen.queryByText(/derivadas excluidas/)).not.toBeInTheDocument();
    });

    it('tabla: ventas y compras vacías con guion y operaciones sumadas', () => {
        render(<InsiderOperationsView result={ok([company()])} days={365} />);
        const rows = screen.getAllByRole('row');
        expect(within(rows[1]).getAllByText('—').length).toBeGreaterThan(0);
        expect(within(rows[1]).getByText('2')).toBeInTheDocument();
        expect(screen.getAllByText(/ops/).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/última/).length).toBeGreaterThan(0);
    });
});
