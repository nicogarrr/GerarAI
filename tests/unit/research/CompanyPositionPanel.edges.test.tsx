import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CompanyPositionPanel } from '@/components/research/CompanyPositionPanel';
import type { PortfolioHolding } from '@/lib/actions/portfolio.actions';

// Supervivientes de mutación (ronda 3): ramas del panel que ningún test fijaba.
const holding = (over: Partial<PortfolioHolding> = {}): PortfolioHolding => ({
    symbol: 'TEST', quantity: 10, avgPrice: 100, costReviewMessage: null, currentPrice: 150,
    valuationHold: null, value: 1350, cost: 900, gain: 450, gainPercent: 50, nativeCurrency: 'USD',
    baseCurrency: 'EUR', fxMissing: false, nativeGain: 500, nativeCost: 1000, valueMissing: false,
    firstBuyDate: '2025-01-01', holdingDays: 300, fiscalBucket: 'corto_plazo', ...over,
});
const held = (over: Partial<PortfolioHolding> = {}, weightPercent: number | null = 39.7, positionsAsOf: string | null = '2026-10-27') =>
    ({ status: 'held' as const, holding: holding(over), weightPercent, positionsAsOf });
const gainCell = () => screen.getByText('Plusvalía latente').parentElement!.querySelector('dd')!;

beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })); });
afterEach(() => vi.unstubAllGlobals());

describe('Company position panel edge branches', () => {
    it('colours a gain green, a loss red and a zero gain neutral', () => {
        const a = render(<CompanyPositionPanel context={held()} />);
        expect(gainCell()).toHaveClass('text-emerald-300');
        a.unmount();
        const b = render(<CompanyPositionPanel context={held({ gain: -120, gainPercent: -13.3 })} />);
        expect(gainCell()).toHaveClass('text-red-300');
        expect(gainCell()).toHaveTextContent('-120,00 € (-13,3 %)');
        b.unmount();
        render(<CompanyPositionPanel context={held({ gain: 0, gainPercent: 0 })} />);
        expect(gainCell()).toHaveClass('text-gray-100');
        expect(gainCell()).toHaveTextContent('0,00 €');
    });
    it('keeps an unknown gain neutral even when the stored gain is positive', () => {
        render(<CompanyPositionPanel context={held({ cost: 0, gain: 450 })} />);
        expect(gainCell()).toHaveClass('text-gray-100');
        expect(gainCell()).not.toHaveClass('text-emerald-300');
    });
    it('hides the native gain line for a base-currency holding and under a suspended valuation', () => {
        const a = render(<CompanyPositionPanel context={held({ nativeCurrency: 'EUR', nativeGain: 450 })} />);
        expect(screen.queryByText(/ en EUR$/)).not.toBeInTheDocument();
        a.unmount();
        render(<CompanyPositionPanel context={held({ valuationHold: { reason: 'Split', effectiveDate: null } })} />);
        expect(screen.queryByText(/en USD/)).not.toBeInTheDocument();
        expect(gainCell()).toHaveTextContent('N/D');
    });
    it('hides the native gain when the native cost is under review', () => {
        render(<CompanyPositionPanel context={held({ costReviewMessage: 'Coste en revisión.' })} />);
        expect(screen.queryByText(/en USD/)).not.toBeInTheDocument();
    });
    it('shows N/D and no gain when the value is missing even with a known cost', () => {
        render(<CompanyPositionPanel context={held({ valueMissing: true })} />);
        expect(screen.getByText('Valor').parentElement).toHaveTextContent('N/D');
        expect(gainCell()).toHaveTextContent('N/D');
        expect(screen.queryByText(/Coste de adquisición desconocido/)).not.toBeInTheDocument();
        expect(screen.queryByText(/Sin coste en EUR/)).not.toBeInTheDocument();
    });
    it('omits the weight footnote without a weight and the first-buy row without a date', () => {
        render(<CompanyPositionPanel context={held({ firstBuyDate: null }, null, null)} />);
        expect(screen.queryByText('de las posiciones con valor')).not.toBeInTheDocument();
        expect(screen.queryByText('Primera compra')).not.toBeInTheDocument();
        expect(screen.getByText('Datos de tu cartera.')).toBeVisible();
    });
    it('shows the first purchase date', () => {
        render(<CompanyPositionPanel context={held()} />);
        expect(screen.getByText('Primera compra').parentElement).toHaveTextContent('1 ene 2025');
    });
    it('prints the average price without a symbol when the native currency is not an ISO code', () => {
        render(<CompanyPositionPanel context={held({ nativeCurrency: '??', nativeGain: 500 })} />);
        const cell = screen.getByText('Coste medio').parentElement!;
        expect(cell).toHaveTextContent('100');
        expect(cell).not.toHaveTextContent('$');
        expect(screen.queryByText(/en \?\?/)).not.toBeInTheDocument();
    });
    it('shows only the suspension notice when a suspended valuation also has no value', () => {
        render(<CompanyPositionPanel context={held({ valueMissing: true, valuationHold: { reason: 'Split', effectiveDate: null } })} />);
        expect(screen.getByRole('status')).toHaveTextContent('Valoración en suspensión: Split');
        expect(screen.queryByText(/falta el precio o el tipo de cambio/)).not.toBeInTheDocument();
    });
    it('treats a negative average price as unknown cost', () => {
        render(<CompanyPositionPanel context={held({ avgPrice: -1 })} />);
        expect(screen.getByText('Coste medio').parentElement).toHaveTextContent('N/D');
        expect(screen.getByRole('status')).toHaveTextContent('Coste de adquisición desconocido');
    });
});
