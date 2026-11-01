import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { WalkForwardBacktestResult } from '@/lib/actions/propicks-backtest.actions';
import WalkForwardResults from '@/components/proPicks/WalkForwardResults';
import StrategyFactsheet from '@/components/proPicks/StrategyFactsheet';
import { categoryNeutralNote } from '@/components/proPicks/category-display';
import { LocaleProvider } from '@/lib/i18n/client';

const result = {
    months: 12, picksPorMes: 5, retornoNeto: 14.5, retornoBruto: 16.2, spy: 10.1, sharpe: 1.234, sortino: 1.5,
    maxDD: -8.25, turnover: 35,
    tablaMensual: [
        { asOf: '2026-01-31T23:59:59.000Z', picks: ['MSFT', 'NVDA'], retNeto: 2.5, spy: 1.2, turnover: 40 },
        { asOf: '2026-02-28T23:59:59.000Z', picks: ['AAPL'], retNeto: -1.5, spy: 0.4, turnover: 30 },
    ],
} as unknown as WalkForwardBacktestResult;

const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

describe('Pro Picks en inglés: walk-forward, ficha de estrategia y nota de categorías', () => {
    it('el walk-forward sale en inglés con números en formato inglés', () => {
        en(<WalkForwardResults result={result} />);
        expect(screen.getAllByText('Point-in-time walk-forward backtest').length).toBeGreaterThan(0);
        expect(screen.getByText(/12 months simulated, 5 picks per month/)).toBeTruthy();
        expect(screen.getByText('Net return')).toBeTruthy();
        expect(screen.getByText('+14.50%')).toBeTruthy();
        expect(screen.getByText('SPY (same period)')).toBeTruthy();
        expect(screen.getByText('Monthly performance')).toBeTruthy();
        expect(screen.getByRole('columnheader', { name: 'Turnover' })).toBeTruthy();
        expect(screen.getByText(/Period: Jan 31, 2026 - Feb 28, 2026/)).toBeTruthy();
        expect(document.body.textContent).toContain('Short sample: 12 months.');
        expect(document.body.textContent).not.toMatch(/meses|Rotación|Retorno/);
    });

    it('sin meses, el estado vacío sale en inglés; en español sigue igual', () => {
        const empty = { ...result, tablaMensual: [] } as unknown as WalkForwardBacktestResult;
        const { unmount } = en(<WalkForwardResults result={empty} />);
        expect(screen.getByText('No months have been simulated')).toBeTruthy();
        unmount();
        render(<WalkForwardResults result={empty} />);
        expect(screen.getByText('Ningún mes se ha simulado')).toBeTruthy();
    });

    it('la ficha de estrategia sale en inglés', () => {
        en(<StrategyFactsheet strategyId="x" name="Quality" description="d" available backtest={result} />);
        expect(screen.getByText("Global backtest, not this strategy's")).toBeTruthy();
        expect(screen.getByText('Net Sharpe')).toBeTruthy();
        expect(screen.getByText('1.23')).toBeTruthy();
        expect(screen.getByText('Excess vs SPY')).toBeTruthy();
        expect(screen.getByText('+4.40%')).toBeTruthy();
        expect(document.body.textContent).not.toMatch(/Retorno|Sin dato|Período/);
    });

    it('la ficha sin métricas y sin oferta del motor sale en inglés', () => {
        const { unmount } = en(<StrategyFactsheet strategyId="x" name="Quality" description="d" available backtest={null} />);
        expect(screen.getByText('No performance metrics')).toBeTruthy();
        expect(screen.getByText('Why there are no figures here')).toBeTruthy();
        unmount();
        en(<StrategyFactsheet strategyId="nope" name="Quality" description="d" available={false} />);
        expect(document.body.textContent).toContain("but the engine doesn't offer it");
    });

    it('la nota de categorías neutras sale en inglés y en español igual', () => {
        expect(categoryNeutralNote(['value', 'momentum'], 20, 'en')?.text).toMatch(
            /^Valuation, Momentum: data missing for the 20 picks in this run \(missing per-company CFROI and WACC; missing the 12-month price series\)/,
        );
        expect(categoryNeutralNote([], 12, 'en')?.text).toMatch(/All 6 funnel categories have data for the 12 picks/);
        expect(categoryNeutralNote(['value'], 3)?.text).toMatch(/^Valoración: sin datos en los 3 picks/);
    });
});
