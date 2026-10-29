import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CompanyPositionPanel } from '@/components/research/CompanyPositionPanel';
import type { PortfolioHolding } from '@/lib/actions/portfolio.actions';

const holding = (over: Partial<PortfolioHolding> = {}): PortfolioHolding => ({
    symbol: 'TEST', quantity: 10, avgPrice: 100, costReviewMessage: null, currentPrice: 150,
    valuationHold: null, value: 1350, cost: 900, gain: 450, gainPercent: 50, nativeCurrency: 'USD',
    baseCurrency: 'EUR', fxMissing: false, nativeGain: 500, nativeCost: 1000, valueMissing: false,
    firstBuyDate: '2025-01-01', holdingDays: 300, fiscalBucket: 'corto_plazo', ...over,
});
const held = (over: Partial<PortfolioHolding> = {}, weightPercent: number | null = 39.7) =>
    ({ status: 'held' as const, holding: holding(over), weightPercent, positionsAsOf: '2026-10-27' });
const value = (label: string) => screen.getByText(label).parentElement!;

// Panel consulta el ancho del viewport; jsdom no trae matchMedia.
beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })); });
afterEach(() => vi.unstubAllGlobals());

describe('Company position panel with the same figures as the portfolio', () => {
    it('shows quantity, cost, base value, gain with native detail, weight and date', () => {
        render(<CompanyPositionPanel context={held()} />);
        expect(screen.getByRole('heading', { name: 'Tu posición' })).toBeVisible();
        expect(screen.getByText(/Datos de tu cartera a 27 oct 2026/)).toBeVisible();
        expect(value('Acciones')).toHaveTextContent('10');
        expect(value('Coste medio')).toHaveTextContent('100,00 US$');
        expect(value('Valor')).toHaveTextContent('1.350,00 €');
        expect(value('Plusvalía latente')).toHaveTextContent('450,00 € (+50,0 %)');
        expect(value('Plusvalía latente')).toHaveTextContent('500,00 US$ en USD');
        expect(value('Peso')).toHaveTextContent('39,7 %de las posiciones con valor');
        expect(screen.getByRole('link', { name: 'Ver en la cartera' })).toHaveAttribute('href', '/portfolio');
    });
    it('never fills a cost under review, a suspended valuation or a missing FX with zeros', () => {
        const { unmount } = render(<CompanyPositionPanel context={held({ costReviewMessage: 'Divisa del coste de IBKR sin verificar.' })} />);
        expect(value('Coste medio')).toHaveTextContent('En revisión');
        expect(value('Plusvalía latente')).toHaveTextContent('N/D');
        expect(screen.getByRole('status')).toHaveTextContent('Divisa del coste de IBKR sin verificar.');
        unmount();
        const second = render(<CompanyPositionPanel context={held({ valuationHold: { reason: 'Split sin precio verificado', effectiveDate: null } }, null)} />);
        expect(value('Valor')).toHaveTextContent('N/D');
        expect(value('Peso')).toHaveTextContent('N/D');
        expect(screen.getByRole('status')).toHaveTextContent('Valoración en suspensión: Split sin precio verificado');
        second.unmount();
        render(<CompanyPositionPanel context={held({ fxMissing: true, valueMissing: true }, null)} />);
        expect(screen.getByRole('status')).toHaveTextContent('Sin valor en EUR: falta el precio o el tipo de cambio.');
        expect(screen.queryByText(/0,00 €/)).not.toBeInTheDocument();
    });
    it('distinguishes unknown acquisition cost from missing price or FX', () => {
        render(<CompanyPositionPanel context={held({ avgPrice: 0, cost: 0, nativeCost: null,
            costReviewMessage: null, fxMissing: true, valueMissing: false })} />);
        expect(value('Coste medio')).toHaveTextContent('N/D');
        expect(value('Valor')).toHaveTextContent('1.350,00 €');
        expect(value('Plusvalía latente')).toHaveTextContent('N/D');
        expect(screen.getByRole('status')).toHaveTextContent('Coste de adquisición desconocido');
        expect(screen.queryByText(/falta el precio o el tipo de cambio/)).not.toBeInTheDocument();
        expect(screen.queryByText('0,00 US$')).not.toBeInTheDocument();
    });
    it('keeps a known native average cost when only the historical FX of the base cost is missing', () => {
        // Ledger con una compra sin cambio BCE de su fecha: cost_basis_base null
        // (cost 0 en la acción) pero precio medio nativo y valor actual conocidos.
        render(<CompanyPositionPanel context={held({ avgPrice: 100, cost: 0, gain: 0, nativeCost: 1000,
            nativeGain: 500, costReviewMessage: null, fxMissing: true, valueMissing: false })} />);
        expect(value('Coste medio')).toHaveTextContent('100,00 US$');
        expect(value('Valor')).toHaveTextContent('1.350,00 €');
        expect(value('Plusvalía latente')).toHaveTextContent('N/D');
        expect(value('Plusvalía latente')).toHaveTextContent('500,00 US$ en USD');
        expect(screen.getByRole('status')).toHaveTextContent('Sin coste en EUR: falta el tipo de cambio de alguna compra.');
        expect(screen.queryByText(/Coste de adquisición desconocido/)).not.toBeInTheDocument();
    });
    it('renders nothing without a position and an explicit message when loading failed', () => {
        const { container, unmount } = render(<CompanyPositionPanel context={{ status: 'not_held' }} />);
        expect(container).toBeEmptyDOMElement();
        unmount();
        render(<CompanyPositionPanel context={{ status: 'error', message: 'No se pudo cargar tu posición en esta empresa.' }} />);
        expect(screen.getByRole('status')).toHaveTextContent('No se pudo cargar tu posición en esta empresa.');
        expect(screen.getByRole('link', { name: 'Ir a la cartera' })).toHaveAttribute('href', '/portfolio');
    });
});
