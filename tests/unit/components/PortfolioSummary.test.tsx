import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import PortfolioSummary from '@/components/portfolio/PortfolioSummary';
import type { PortfolioHolding, PortfolioSummary as Summary } from '@/lib/actions/portfolio.actions';
import { formatMoney, formatPercent } from '@/lib/format';

function holding(overrides: Partial<PortfolioHolding> = {}): PortfolioHolding {
    return {
        symbol: 'AAPL',
        quantity: 10,
        avgPrice: 100,
        currentPrice: 120,
        valuationHold: null,
        value: 1200,
        cost: 1000,
        gain: 200,
        gainPercent: 20,
        nativeCurrency: 'USD',
        baseCurrency: 'EUR',
        fxMissing: false,
        nativeGain: 200,
        nativeCost: 1000,
        valueMissing: false,
        firstBuyDate: '2025-01-02',
        holdingDays: 300,
        fiscalBucket: 'corto_plazo',
        ...overrides,
    };
}

function summary(overrides: Partial<Summary> = {}): Summary {
    return {
        totalValue: 1700,
        totalCost: 1000,
        totalGain: 200,
        totalGainPercent: 20,
        holdings: [holding()],
        equityValue: 1200,
        cash: 500,
        baseCurrency: 'EUR',
        status: 'ok',
        missingFx: [],
        valuationHold: [],
        ...overrides,
    };
}

// Intl usa espacios duros (U+00A0/U+202F); toHaveTextContent normaliza el
// texto recibido a espacios simples, así que el esperado se normaliza igual.
const norm = (s: string) => s.replace(/\s+/g, ' ');
const money = (v: number) => norm(formatMoney(v, 'EUR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

/** Valor de la tarjeta cuyo rótulo es `label` (el <p> siguiente al rótulo). */
function cardValue(label: string): HTMLElement {
    const value = screen.getByText(label).nextElementSibling;
    if (!(value instanceof HTMLElement)) throw new Error(`sin valor para ${label}`);
    return value;
}

describe('PortfolioSummary', () => {
    it('coste IBKR en revisión oculta los totales de coste y ganancia, no el valor', () => {
        render(<PortfolioSummary summary={summary({ holdings: [holding({ costReviewMessage: 'Revisión IBKR', fxMissing: true })] })} />);
        expect(screen.getByRole('status')).toHaveTextContent('diferencias entre el extracto');
        expect(cardValue('Coste de las posiciones')).toHaveTextContent('N/D');
        expect(cardValue('Ganancia/Pérdida')).toHaveTextContent('N/D');
        expect(cardValue('Valor total (neto)')).toHaveTextContent(money(1700));
    });
    it('pinta valor neto, coste, G/P y rendimiento en la divisa base con formato es-ES', () => {
        render(<PortfolioSummary summary={summary()} />);
        expect(cardValue('Valor total (neto)')).toHaveTextContent(money(1700));
        expect(screen.getByText(/Patrimonio neto: RV/)).toHaveTextContent(`RV ${money(1200)} + caja ${money(500)}`);
        expect(cardValue('Coste de las posiciones')).toHaveTextContent(money(1000));
        expect(cardValue('Ganancia/Pérdida')).toHaveTextContent(money(200));
        const rendimiento = screen.getByText('Rendimiento').nextElementSibling as HTMLElement;
        expect(rendimiento).toHaveTextContent(norm(formatPercent(20, { fromRatio: false, digits: 2, signDisplay: 'always' })));
        // es-ES: coma decimal y símbolo de euro, nunca "1,700.00".
        expect(cardValue('Valor total (neto)').textContent).toMatch(/1\.?700,00\s€/);
    });

    it('ganancia en verde y pérdida en rojo', () => {
        const { unmount } = render(<PortfolioSummary summary={summary()} />);
        expect(cardValue('Ganancia/Pérdida')).toHaveClass('text-good');
        unmount();
        render(<PortfolioSummary summary={summary({ totalGain: -50, totalGainPercent: -5, holdings: [holding({ gain: -50, gainPercent: -5 })] })} />);
        expect(cardValue('Ganancia/Pérdida')).toHaveClass('text-bad');
        expect(cardValue('Ganancia/Pérdida').textContent).toMatch(/^-/);
    });

    it('sin base de coste (F2): coste, G/P y rendimiento son N/D, nunca 0,00', () => {
        render(
            <PortfolioSummary
                summary={summary({ totalCost: 0, totalGain: 0, totalGainPercent: 0, holdings: [holding({ cost: 0, gain: 0, gainPercent: 0 })] })}
            />,
        );
        expect(cardValue('Coste de las posiciones')).toHaveTextContent(/^N\/D$/);
        expect(cardValue('Ganancia/Pérdida')).toHaveTextContent(/^N\/D$/);
        expect(screen.getByText('Rendimiento').nextElementSibling).toHaveTextContent(/^N\/D$/);
        expect(screen.queryByText(/0,00\s?%/)).not.toBeInTheDocument();
    });

    it('cartera vacía (F31): sin "+0,00 %" en verde', () => {
        render(<PortfolioSummary summary={summary({ holdings: [], totalValue: 0, totalCost: 0, totalGain: 0, totalGainPercent: 0, equityValue: 0, cash: 0 })} />);
        expect(screen.getByText('Rendimiento').nextElementSibling).toHaveTextContent(/^N\/D$/);
        expect(screen.getByText('Rendimiento').nextElementSibling).not.toHaveClass('text-good');
    });

    it('cartera vacía sin caja: Valor total es N/D, no 0,00 EUR, y sin línea de patrimonio', () => {
        render(<PortfolioSummary summary={summary({ holdings: [], totalValue: 0, totalCost: 0, totalGain: 0, totalGainPercent: 0, equityValue: 0, cash: 0 })} />);
        expect(cardValue('Valor total (neto)')).toHaveTextContent(/^N\/D$/);
        expect(screen.queryByText(/Patrimonio neto: RV/)).not.toBeInTheDocument();
    });

    it('sin posiciones pero con caja: el valor total (la caja) sigue siendo un dato', () => {
        render(<PortfolioSummary summary={summary({ holdings: [], totalValue: 500, totalCost: 0, totalGain: 0, totalGainPercent: 0, equityValue: 0, cash: 500 })} />);
        expect(cardValue('Valor total (neto)').textContent).toMatch(/500,00\s€/);
        expect(screen.getByText(/Patrimonio neto: RV/)).toBeInTheDocument();
    });

    it('avisa de lo que los totales excluyen (FX ausente y valoración en suspensión)', () => {
        render(
            <PortfolioSummary
                summary={summary({
                    status: 'incomplete_fx',
                    missingFx: [{ currency: 'HKD' }],
                    valuationHold: [{ ticker: 'KRKNF', reason: 'split', effective_date: null }],
                })}
            />,
        );
        expect(screen.getByText(/excluyen 1 saldo o posición sin tipo de cambio válido/)).toBeInTheDocument();
        expect(screen.getByText(/valoración pendiente tras un split.*\(KRKNF\)/)).toBeInTheDocument();
    });
});

describe('PortfolioSummary: posiciones fuera del coste', () => {
    it('dice cuántas posiciones quedan fuera de coste y rendimiento', () => {
        render(<PortfolioSummary summary={summary({ totalsExcluded: 2, holdings: [holding(), holding({ symbol: 'NOFX', fxMissing: true, valueMissing: true })] })} />);
        expect(screen.getByText(/No incluye 2 posiciones sin precio, tipo de cambio o en revisión/)).toBeInTheDocument();
    });
    it('sin exclusiones no añade la nota', () => {
        render(<PortfolioSummary summary={summary()} />);
        expect(screen.queryByText(/No incluye/)).toBeNull();
    });
});
