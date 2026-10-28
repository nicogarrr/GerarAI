import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import PortfolioScores from '@/components/portfolio/PortfolioScores';
import PortfolioTearsheet from '@/components/portfolio/PortfolioTearsheet';
import { PortfolioValueBreakdown, fxBasisText } from '@/components/portfolio/PortfolioValueBreakdown';

describe('PortfolioScores', () => {
    it('sin datos no es un cero: guion, etiqueta y lista de faltantes', () => {
        render(<PortfolioScores scores={{ quality: null, growth: 55.5, value: null, dividend: null, cagr3y: null }} />);
        expect(screen.getAllByText('sin datos')).toHaveLength(4);
        expect(screen.getByText('55,50')).toBeInTheDocument();
        expect(screen.getByText(/Sin datos para: .*Retorno acumulado/)).toBeInTheDocument();
        expect(screen.getByText(/Una puntuación sin datos no es un 0/)).toBeInTheDocument();
    });

    it('todos con dato: sin aviso de faltantes; 0 real se muestra como 0,00', () => {
        render(<PortfolioScores scores={{ quality: 0, growth: 10, value: 20, dividend: 30, cagr3y: 12.345 }} />);
        expect(screen.queryByText(/Sin datos para/)).not.toBeInTheDocument();
        expect(screen.getByText('0,00')).toBeInTheDocument();
        expect(document.body.textContent).toMatch(/12,35\s?%|12,34\s?%/);
    });
});

describe('PortfolioTearsheet', () => {
    const base = (m: Record<string, unknown> = {}, extra: Record<string, unknown> = {}): any => ({
        metrics: { sharpe: 1.234, max_drawdown: -0.2345, win_rate: 0.55, n_observations: 120, cumulative_return: 0.087, best_day: 0.05, worst_day: -0.06, ...m },
        exposure: null, ...extra,
    });

    it.each([[null], [{ metrics: null }], [base({ n_observations: 1 })], [base({ n_observations: 0 })]])('datos insuficientes: mensaje, sin cifras (%#)', (ts) => {
        render(<PortfolioTearsheet tearsheet={ts as any} />);
        expect(screen.getByText(/No hay retornos suficientes/)).toBeInTheDocument();
        expect(screen.queryByText('Sharpe')).not.toBeInTheDocument();
    });

    it('con 2 observaciones ya calcula', () => {
        render(<PortfolioTearsheet tearsheet={base({ n_observations: 2 })} />);
        expect(screen.getByText('Sharpe')).toBeInTheDocument();
    });

    it('formatea ratios como porcentaje y Sharpe con 2 decimales', () => {
        render(<PortfolioTearsheet tearsheet={base()} />);
        expect(screen.getByText('1,23')).toBeInTheDocument();
        expect(screen.getByText(/-23,45\s?%/)).toBeInTheDocument();
        expect(screen.getByText(/55,00\s?%/)).toBeInTheDocument();
        expect(document.body.textContent).toMatch(/120 sesiones · Ret\. acumulado\s+8,70\s?%/);
    });

    it('Sharpe null: N/D y sin color verde por defecto', () => {
        render(<PortfolioTearsheet tearsheet={base({ sharpe: null })} />);
        const value = screen.getByText('Sharpe').previousSibling!.previousSibling as Element;
        expect(value.getAttribute('class')).toContain('text-gray-400');
        expect(screen.getByText('Sharpe').previousElementSibling!.textContent).toBe('N/D');
    });

    it('Sharpe negativo en rojo, positivo en verde', () => {
        const { unmount } = render(<PortfolioTearsheet tearsheet={base({ sharpe: -0.5 })} />);
        expect(document.querySelector('svg.text-red-400')).not.toBeNull();
        unmount();
        render(<PortfolioTearsheet tearsheet={base({ sharpe: 0.5 })} />);
        expect(document.querySelector('svg.text-green-400')).not.toBeNull();
    });

    it('exposicion: posiciones y fecha de corte', () => {
        render(<PortfolioTearsheet tearsheet={base({}, { exposure: { n_positions: 12, snapshot_date: '2026-10-01' } })} />);
        expect(document.body.textContent).toContain('12 posiciones');
        expect(document.body.textContent).toMatch(/datos hasta el 1 oct/);
    });
});

const summary = (over: Record<string, unknown> = {}): any => ({
    equityValue: 10000, totalValue: 8000, cash: -2000, cashAssets: 500, marginDebt: 2500, baseCurrency: 'EUR', status: 'ok', ...over,
});

describe('PortfolioValueBreakdown', () => {
    it('separa caja positiva y deuda de margen (no las netea)', () => {
        render(<PortfolioValueBreakdown summary={summary()} />);
        expect(screen.getByText('Caja (saldos positivos)').nextSibling!.textContent).toMatch(/500/);
        const debt = screen.getByText('Deuda de margen').nextSibling as HTMLElement;
        expect(debt.textContent).toMatch(/2\.?500/);
        expect(debt.className).toContain('text-amber');
        expect(screen.queryByText('Caja / margen neto')).not.toBeInTheDocument();
    });

    it('sin deuda: no se resalta', () => {
        render(<PortfolioValueBreakdown summary={summary({ marginDebt: 0 })} />);
        expect((screen.getByText('Deuda de margen').nextSibling as HTMLElement).className).not.toContain('amber');
    });

    it('sin desglose en el payload: una sola linea neta', () => {
        render(<PortfolioValueBreakdown summary={summary({ cashAssets: undefined, marginDebt: undefined })} />);
        expect(screen.getByText('Caja / margen neto').nextSibling!.textContent).toMatch(/-\s?2\.?000/);
        expect(screen.queryByText('Deuda de margen')).not.toBeInTheDocument();
    });

    it('solo uno de los dos presente tampoco inventa el desglose', () => {
        render(<PortfolioValueBreakdown summary={summary({ marginDebt: undefined })} />);
        expect(screen.getByText('Caja / margen neto')).toBeInTheDocument();
    });

    it('FX incompleto: patrimonio parcial y aviso', () => {
        render(<PortfolioValueBreakdown summary={summary({ status: 'incomplete_fx' })} />);
        expect(screen.getByText('Patrimonio neto (parcial)')).toBeInTheDocument();
        expect(screen.getByText(/Faltan tipos de cambio/)).toBeInTheDocument();
    });

    it('estado ok: sin parcial ni aviso', () => {
        render(<PortfolioValueBreakdown summary={summary()} />);
        expect(screen.getByText('Patrimonio neto')).toBeInTheDocument();
        expect(screen.queryByText(/Faltan tipos de cambio/)).not.toBeInTheDocument();
    });
});

describe('fxBasisText', () => {
    it('sin tipos: null', () => {
        expect(fxBasisText(summary())).toBeNull();
        expect(fxBasisText(summary({ fxRates: [] }))).toBeNull();
    });

    it('distingue caja de posiciones y da el tipo con 4 decimales', () => {
        const text = fxBasisText(summary({ fxRates: [
            { scope: 'cash', currency: 'USD', rate: 0.8769, as_of: '2026-09-25' },
            { scope: 'positions', currency: 'CAD', rate: 0.6, as_of: '2026-09-26' },
        ] }))!;
        expect(text).toContain('Caja: 1 USD = 0,8769');
        expect(text).toContain('Posiciones: 1 CAD = 0,6000');
        expect(text.split(' · ')).toHaveLength(2);
    });
});
