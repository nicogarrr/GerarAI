import axe from 'axe-core';
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// axe heading-order (WCAG 1.3.1 / 2.4.6) en las pestañas de /portfolio. El
// barrido de r5-a11y (build de producción, 390 y 1440 px, 12-nov-2026) abrió
// cada pestaña: «Posiciones», «Movimientos» y «Factores» saltaban del h1 de la
// página («Resumen de cartera») a un h3 (CardTitle por defecto). Radix no
// pinta los paneles inactivos, así que el título de la tarjeta de cada pestaña
// es el primer titular bajo el h1 y debe ser h2. tests/unit/a11y/heading-order
// cubre la pestaña Resumen.

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteHolding: vi.fn(), refreshPortfolioHoldings: vi.fn(), deleteTransaction: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: () => null }));
vi.mock('@/components/common/TrackedAnalysisStatus', () => ({ TrackedAnalysisStatus: () => null }));
vi.mock('@/components/common/ExtendedHoursLine', () => ({ default: () => null }));
vi.mock('@/components/common/AnalystTargetLine', () => ({ default: () => null }));
vi.mock('@/components/portfolio/HoldingSignals', () => ({ DcaLevelChip: () => null, FairValueLine: () => null, useHoldingSignals: () => null }));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/ImportImageButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/EditTransactionDialog', () => ({ default: () => null }));

import PortfolioHoldings from '@/components/portfolio/PortfolioHoldings';
import PortfolioScores from '@/components/portfolio/PortfolioScores';
import PortfolioTransactions from '@/components/portfolio/PortfolioTransactions';

async function headingOrder(node: Element) {
    const result = await axe.run(node, { runOnly: { type: 'rule', values: ['heading-order'] } });
    return result.violations.flatMap((v) => v.nodes.map((n) => n.html));
}
const firstBelowH1 = (node: Element) => {
    const hs = Array.from(node.querySelectorAll('h1,h2,h3,h4,h5,h6'));
    return hs[1] ? `${hs[1].tagName.toLowerCase()} ${hs[1].textContent?.trim()}` : null;
};
const inPage = (panel: React.ReactNode) => (
    <main>
        <h1>Resumen de cartera</h1>
        <div role="tabpanel">{panel}</div>
    </main>
);

const holding = {
    symbol: 'AAPL', quantity: 10, avgPrice: 100, currentPrice: 120, valuationHold: null, value: 1200, cost: 1000, gain: 200,
    gainPercent: 20, nativeCurrency: 'EUR', baseCurrency: 'EUR', fxMissing: false, nativeGain: null, nativeCost: null,
    valueMissing: false, firstBuyDate: '2024-01-15', holdingDays: 400, fiscalBucket: 'largo_plazo',
};
const tx = { _id: '1', symbol: 'AAPL', type: 'buy', quantity: 3, price: 10.5, date: '2026-01-15', currency: 'EUR' };

describe('a11y: pestañas de la cartera sin saltos de titular', () => {
    it('Posiciones: «Posiciones actuales» es h2 bajo el h1', async () => {
        const { container } = render(inPage(<PortfolioHoldings holdings={[holding] as never} userId="u" />));
        expect(firstBelowH1(container)).toBe('h2 Posiciones actuales');
        expect(await headingOrder(container)).toEqual([]);
    });

    it('Movimientos: «Historial de movimientos» es h2 bajo el h1', async () => {
        const { container } = render(inPage(<PortfolioTransactions transactions={[tx] as never} userId="u" />));
        expect(firstBelowH1(container)).toBe('h2 Historial de movimientos');
        expect(await headingOrder(container)).toEqual([]);
    });

    it('Factores: «Indicadores históricos» es h2 bajo el h1', async () => {
        const { container } = render(inPage(<PortfolioScores scores={{ quality: 70, growth: 60, value: 50, dividend: null, cagr3y: 12 }} />));
        expect(firstBelowH1(container)).toBe('h2 Indicadores históricos');
        expect(await headingOrder(container)).toEqual([]);
    });
});
