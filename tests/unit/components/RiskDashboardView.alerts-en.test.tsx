import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/risk.actions', () => ({ getRiskDashboard: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import RiskDashboardView from '@/components/risk/RiskDashboardView';
import { LocaleProvider } from '@/lib/i18n/client';

// Frases reales de las alertas (valuation/portfolio_risk.py, leídas del .py):
// cada f-string se rellena en orden con los valores dados.
const PY = readFileSync('data-engine/app/valuation/portfolio_risk.py', 'utf8');
const fstring = (re: RegExp, ...values: string[]): string => {
    const m = re.exec(PY);
    if (!m) throw new Error(`no encontrado en portfolio_risk.py: ${re}`);
    let i = 0;
    return m[1].replace(/\{[^}]+\}/g, () => values[i++]);
};
const OVER_20 = fstring(/"message": f"(\{position\['ticker'\]\} supera el 20[^"]+)"/, 'ASTS');
const PRE_FCF = fstring(/"message": f"(\{position\['ticker'\]\} es pre-FCF[^"]+)"/, 'RKLB');
const NET_CASH = fstring(/message = f"(El saldo neto de caja[^"]+)"/, 'EUR') + fstring(/message \+= f"([^"]+)"/, 'USD (-1,250.00)');
const CASH = fstring(/message = f"(El saldo de caja en [^"]+)"/, 'USD');

const dashboard = {
    status: 'ok', base_currency: 'EUR', total_value: 10000, equity_value: 9000, top_1_weight: 0.25, top_5_weight: 0.8,
    weight_basis: 'gross_equity', cash: { EUR: -200 }, sector_exposure: {}, factor_exposure: {},
    positions: [{ ticker: 'ASTS', name: 'AST SpaceMobile', sector: 'Technology', market_value: 2500, weight: 0.25 }],
    alerts: [
        { ticker: 'ASTS', severity: 'high', message: OVER_20, metric_value: 0.25, threshold: 0.2 },
        { ticker: 'RKLB', severity: 'medium', message: PRE_FCF, metric_value: 0.12, threshold: 0.1 },
        { ticker: null, severity: 'high', message: NET_CASH, metric_value: -200, threshold: 0 },
        { ticker: null, severity: 'high', message: CASH, metric_value: -50, threshold: 0 },
    ],
};

const renderIn = (locale: 'es' | 'en') =>
    render(<LocaleProvider locale={locale}><RiskDashboardView initialDashboard={dashboard as never} /></LocaleProvider>);

describe('RiskDashboardView: alertas del backend en inglés', () => {
    it('las frases de prueba son las del backend', () => {
        expect(OVER_20).toBe('ASTS supera el 20 % de peso en la cartera');
        expect(NET_CASH).toBe('El saldo neto de caja, convertido a EUR, es negativo (saldo negativo en USD (-1,250.00))');
    });
    it('en inglés cada alerta sale en inglés', () => {
        const { container } = renderIn('en');
        expect(screen.getByText('ASTS is more than 20% of the portfolio')).toBeInTheDocument();
        expect(screen.getByText('RKLB is pre-FCF and more than 10% of the portfolio')).toBeInTheDocument();
        expect(screen.getByText('The net cash balance, converted to EUR, is negative (negative balance in USD (-1,250.00))')).toBeInTheDocument();
        expect(screen.getByText('The USD cash balance is negative')).toBeInTheDocument();
        for (const es of [OVER_20, PRE_FCF, NET_CASH, CASH]) expect(container.textContent).not.toContain(es);
    });
    it('en castellano se pinta la frase del backend tal cual', () => {
        renderIn('es');
        for (const es of [OVER_20, PRE_FCF, NET_CASH, CASH]) expect(screen.getByText(es)).toBeInTheDocument();
    });
});
