import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import WalkForwardResults from '@/components/proPicks/WalkForwardResults';
import type { WalkForwardBacktestResult } from '@/lib/actions/propicks-backtest.actions';

const fixture = (over: Partial<WalkForwardBacktestResult> = {}): WalkForwardBacktestResult => ({
    months: 2, picksPorMes: 2, turnover: 50, retornoBruto: 14, retornoNeto: 12,
    spy: -3, sharpe: 1.25, sortino: 2.5, maxDD: -8.12, snapshots: [],
    tablaMensual: [
        { asOf: '2026-01-31T23:59:59Z', picks: ['AAA', 'BBB'], retBruto: 5.3, retNeto: 5, spy: -2, turnover: 50 },
        { asOf: '2026-02-28T23:59:59Z', picks: ['BBB', 'CCC'], retBruto: -0.7, retNeto: -1, spy: 0, turnover: 100 },
    ], ...over,
});

describe('Walk-forward results presentation', () => {
    it('explains missing months instead of displaying fabricated zero performance', () => {
        render(<WalkForwardResults result={fixture({ tablaMensual: [], months: 0, retornoNeto: 0 })} />);
        expect(screen.getByText('Ningún mes se ha simulado')).toBeVisible();
        expect(screen.getByText(/253 cierres anteriores/)).toBeVisible();
        expect(screen.queryByText('Retorno neto')).not.toBeInTheDocument();
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
        expect(screen.queryByText('Metodología del backtest')).not.toBeInTheDocument();
    });

    it('shows percentage points as points, signed returns and explicit baseline limitations', () => {
        render(<WalkForwardResults result={fixture()} />);
        const metric = (label: string) => screen.getByText(label).parentElement!;
        expect(metric('Retorno neto')).toHaveTextContent('+12,00 %');
        expect(metric('Retorno neto')).not.toHaveTextContent('1.200');
        expect(metric('Retorno bruto')).toHaveTextContent('+14,00 %');
        expect(metric('SPY (mismo período)')).toHaveTextContent('-3,00 %');
        expect(metric('Sharpe')).toHaveTextContent('1,25');
        expect(metric('Sortino')).toHaveTextContent('2,50');
        expect(metric('Máx. drawdown')).toHaveTextContent('-8,12 %');
        expect(screen.getByText(/2 meses simulados, 2 picks por mes/)).toBeVisible();
        expect(screen.getByText(/No mide la selección de calidad y valor de ProPicks/)).toBeVisible();
        expect(screen.getByText(/Período:/)).toHaveTextContent('31 ene 2026 - 28 feb 2026');
    });

    it('labels the scrollable monthly table and preserves zero, negative and positive values', () => {
        render(<WalkForwardResults result={fixture()} />);
        const region = screen.getByRole('region', { name: 'Desempeño mensual del backtest' });
        expect(region).toHaveAttribute('tabindex', '0');
        const table = within(region).getByRole('table', { name: /Desempeño mensual del backtest walk-forward/ });
        expect(within(table).getAllByRole('columnheader')).toHaveLength(5);
        const rows = within(table).getAllByRole('row');
        expect(rows).toHaveLength(3);
        expect(rows[1]).toHaveTextContent('AAA, BBB');
        expect(within(rows[1]).getByText('+5,00 %')).toHaveClass('text-green-400');
        expect(within(rows[1]).getByText('-2,00 %')).toHaveClass('text-red-400');
        expect(within(rows[2]).getByText('-1,00 %')).toHaveClass('text-red-400');
        expect(within(rows[2]).getByText('0,00 %')).toHaveClass('text-red-400');
        expect(rows[2]).toHaveTextContent('100 %');
        // Desktop and mobile each retain the same supplied dates and return values.
        expect(screen.getAllByText('AAA, BBB')).toHaveLength(2);
        expect(screen.getAllByText('+5,00 %')).toHaveLength(2);
        expect(screen.getByText('SPY 0,00 %')).toBeInTheDocument();
        expect(screen.getByText('Rotación 100 %')).toBeInTheDocument();
    });

    it('keeps methodology closed until requested and discloses costs and survivorship bias', () => {
        render(<WalkForwardResults result={fixture()} />);
        const summary = screen.getByText('Metodología del backtest');
        const details = summary.closest('details')!;
        expect(details).not.toHaveAttribute('open');
        fireEvent.click(summary);
        expect(details).toHaveAttribute('open');
        expect(within(details).getByText(/15 pb por pata de rotación/)).toBeVisible();
        expect(within(details).getByText(/Rotación media mensual: 50 %/)).toBeVisible();
        expect(within(details).getByText(/Sesgo de supervivencia/)).toBeVisible();
        expect(within(details).getByText(/sin impuestos ni deslizamiento/)).toBeVisible();
        expect(within(details).getByText(/todavía no hay meses suficientes/)).toBeVisible();
        expect(within(details).getByText(/no garantizan rendimientos futuros/)).toBeVisible();
    });
});
