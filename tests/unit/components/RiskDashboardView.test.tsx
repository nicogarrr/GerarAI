import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const getRiskDashboard = vi.fn();
vi.mock('@/lib/actions/risk.actions', () => ({
    getRiskDashboard: () => getRiskDashboard(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import RiskDashboardView from '@/components/risk/RiskDashboardView';

const base = {
    status: 'ok',
    base_currency: 'EUR',
    total_value: 10000,
    equity_value: 9000,
    top_1_weight: 0.25,
    top_5_weight: 0.8,
    weight_basis: 'gross_equity',
    cash: { EUR: 1000, USD: -50 },
    sector_exposure: { Technology: 0.45, Healthcare: 0.2 },
    factor_exposure: { growth: 0.5 },
    positions: [
        { ticker: 'asts', name: 'AST SpaceMobile', sector: 'Technology', market_value: 2500, weight: 0.25 },
        { ticker: ' ', name: 'Sin ticker', sector: null, market_value: null, weight: null },
    ],
    alerts: [
        { ticker: 'ASTS', severity: 'high', message: 'ASTS pesa 25 %', threshold: 0.2 },
        { ticker: 'PRE', severity: 'medium', message: 'PRE pre-FCF', threshold: 0.1 },
        { message: 'Caja USD negativa', severity: 'high', threshold: 0 },
        { ticker: 'X', message: 'Otra', severity: 'low', threshold: 0.5 },
    ],
};

describe('RiskDashboardView: valoración en suspenso', () => {
    it('etiqueta y estado en es-ES, con ticker, motivo y fecha', () => {
        render(<RiskDashboardView initialDashboard={{
            ...base,
            status: 'incomplete_valuation',
            valuation_hold: [{ ticker: 'KRKNF', reason: 'precio dudoso', effective_date: '2026-09-01' }],
        }} />);
        expect(screen.getByText('Valoración en suspenso')).toBeInTheDocument();
        expect(screen.getByText(/KRKNF: precio dudoso/)).toBeInTheDocument();
        expect(screen.getByText(/1 sept 2026/)).toBeInTheDocument();
        expect(screen.getByText('Incompleto: valoración en suspenso')).toBeInTheDocument();
        expect(screen.queryByText(/Valuation hold/i)).not.toBeInTheDocument();
        expect(screen.queryByText('incomplete_valuation')).not.toBeInTheDocument();
    });
    it('sin filas en suspenso no pinta la fila (como missing_fx)', () => {
        render(<RiskDashboardView initialDashboard={{ ...base, valuation_hold: [] }} />);
        expect(screen.queryByText('Valoración en suspenso')).not.toBeInTheDocument();
    });
});

describe('RiskDashboardView', () => {
    it('muestra resumen formateado en español y posiciones enlazadas', () => {
        render(<RiskDashboardView initialDashboard={base} />);
        expect(screen.getByText('Valor total')).toBeInTheDocument();
        expect(screen.getByText(/Valor bruto de las posiciones/)).toBeInTheDocument();
        expect(screen.getByText('Exposición por sector')).toBeInTheDocument();
        expect(screen.getByText(/Tecnología 45,0/)).toBeInTheDocument();
        expect(screen.getByText('Correcto')).toBeInTheDocument();
        const links = screen.getAllByRole('link', { name: 'asts' });
        expect(links[0]).toHaveAttribute('href', '/research/ASTS');
        expect(screen.getByRole('link', { name: /Ver cartera/ })).toHaveAttribute('href', '/portfolio');
        // sin valor ni peso: N/D, nunca inventado
        expect(screen.getAllByText('N/D').length).toBeGreaterThan(0);
    });

    it('explica cada umbral de alerta', () => {
        render(<RiskDashboardView initialDashboard={base} />);
        expect(screen.getByText(/Umbral 20% del valor/)).toBeInTheDocument();
        expect(screen.getByText(/pre-FCF \(todavía/)).toBeInTheDocument();
        expect(screen.getByText(/saldo deudor/)).toBeInTheDocument();
        expect(screen.getByText(/Alerta disparada al superar/)).toBeInTheDocument();
    });

    it('sin alertas distingue estado ok de cobertura incompleta', () => {
        const { rerender } = render(<RiskDashboardView initialDashboard={{ ...base, alerts: [] }} />);
        expect(screen.getByText(/Sin alertas de concentración o liquidez/)).toBeInTheDocument();
        rerender(<RiskDashboardView initialDashboard={{ ...base, status: 'incomplete_fx', alerts: [] }} />);
        expect(screen.getByText(/no permite descartar alertas/)).toBeInTheDocument();
        expect(screen.getByText('Incompleto: faltan tipos de cambio')).toBeInTheDocument();
    });

    it('dashboard nulo muestra estados vacíos', () => {
        render(<RiskDashboardView initialDashboard={null} />);
        expect(screen.getByText(/No hay métricas de riesgo disponibles/)).toBeInTheDocument();
        expect(screen.getByText('Sin posiciones con exposición calculada.')).toBeInTheDocument();
        expect(screen.getByText(/No hay alertas en los datos disponibles/)).toBeInTheDocument();
    });

    it('humaniza campos de FX, caja, procedencia y fechas', () => {
        render(
            <RiskDashboardView
                initialDashboard={{
                    status: 'insufficient_data',
                    base_currency: 'EUR',
                    total_value: null,
                    equity_value: undefined,
                    top_1_weight: 'x',
                    weight_basis: 'with_cash',
                    cash_assets_base: 100,
                    margin_debt_base: 'n',
                    cash: {},
                    cash_native: 'raw',
                    sector_exposure: {},
                    factor_exposure: { a: 'x' },
                    missing_fx: [{ ticker: 'AAA' }, { quote_currency: 'GBP' }, { x: 1 }, 'JPY'],
                    cash_as_of: '2026-10-01',
                    fx_rates: [
                        { scope: 'cash', currency: 'USD', rate: 0.9, as_of: '2026-10-01' },
                        { scope: 'pos', currency: 'GBP', rate: 1.1, as_of: 5 },
                        'mal',
                    ],
                    valuation_dates_differ: true,
                    data_as_of: '2026-10-02T10:00:00Z',
                    provenance: { source: 'CavaAI Postgres', fetched_at: '2026-10-02T10:00:00Z' },
                    flag: true,
                    other_flag: false,
                    some_key: 'valor',
                    trace: 'oculto',
                    positions: [],
                    alerts: [],
                }}
            />,
        );
        expect(screen.getAllByText('N/D (faltan tipos de cambio)')).toHaveLength(2);
        expect(screen.getByText('Datos insuficientes')).toBeInTheDocument();
        expect(screen.getByText('Total con caja')).toBeInTheDocument();
        expect(screen.getByText('Sin saldos')).toBeInTheDocument();
        expect(screen.getByText('Sin datos')).toBeInTheDocument();
        expect(screen.getByText('AAA, GBP, ?, JPY')).toBeInTheDocument();
        expect(screen.getByText(/Caja: 1 USD = 0,9000 EUR/)).toBeInTheDocument();
        expect(screen.getByText(/Posiciones: 1 GBP = 1,1000 EUR/)).toBeInTheDocument();
        expect(screen.getByText(/Posiciones y caja a fechas distintas/)).toBeInTheDocument();
        expect(screen.getByText(/Base de datos de GerarAI/)).toBeInTheDocument();
        expect(screen.getByText('Sí')).toBeInTheDocument();
        expect(screen.getByText('No')).toBeInTheDocument();
        expect(screen.getByText('Some key')).toBeInTheDocument();
        expect(screen.queryByText('oculto')).not.toBeInTheDocument();
    });

    it('provenance sin fuente o no-objeto', () => {
        render(<RiskDashboardView initialDashboard={{ provenance: {}, data_as_of: null, cash_as_of: '' }} />);
        expect(screen.getByText('Fuente interna')).toBeInTheDocument();
        const r = render(<RiskDashboardView initialDashboard={{ provenance: 'x', status: 'zzz' }} />);
        expect(r.container.textContent).toContain('zzz');
    });

    it('Refrescar vuelve a pedir el dashboard y actualiza tablas', async () => {
        getRiskDashboard.mockResolvedValueOnce({
            ...base,
            total_value: 12345,
            positions: [{ ticker: 'NEW', name: 'Nueva', sector: 'Healthcare', market_value: '100', weight: 0.5 }],
            alerts: [],
        });
        render(<RiskDashboardView initialDashboard={base} />);
        fireEvent.click(screen.getByRole('button', { name: /Refrescar/ }));
        await waitFor(() => expect(screen.getAllByRole('link', { name: 'NEW' }).length).toBeGreaterThan(0));
        expect(getRiskDashboard).toHaveBeenCalledTimes(1);
        expect(screen.getAllByText('Salud').length).toBeGreaterThan(0);
    });

    it('valor no numérico de posición es N/D', () => {
        render(
            <RiskDashboardView
                initialDashboard={{ positions: [{ name: 'Z', as_of: '1', market_value: 'abc', sector: 'Raro', weight: 0.1 }] }}
            />,
        );
        const rows = screen.getAllByRole('row');
        expect(within(rows[1]).getAllByText('N/D').length).toBeGreaterThan(0);
        expect(within(rows[1]).getByText('Raro')).toBeInTheDocument();
    });
});
