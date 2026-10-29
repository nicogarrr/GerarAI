import axe from 'axe-core';
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// axe heading-order (WCAG 1.3.1 / 2.4.6) en las dos pantallas donde Lighthouse
// CI (build de producción, sesión con datos) bajaba la nota de accesibilidad:
// /portfolio saltaba de h1 «Resumen» a h3 «Valor de la cartera» y /taxes de h1
// «Impuestos» a h3 «Informe fiscal 2026». Un lector de pantalla que navega por
// titulares ve un nivel que falta y cree que se ha perdido una sección.

vi.mock('next/navigation', () => ({
    useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
    useSearchParams: () => new URLSearchParams(),
    usePathname: () => '/portfolio',
}));
vi.mock('next/dynamic', () => ({ default: () => () => <div data-testid="nav-chart" /> }));
vi.mock('@/lib/actions/taxes.actions', () => ({
    regenerateTaxReport: vi.fn(), getTaxReport: vi.fn(), getTaxHoldings: vi.fn(), previewTaxFiling: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
vi.mock('@/components/portfolio/PortfolioDataNotice', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioSummary', () => ({ default: () => <div>summary</div> }));
vi.mock('@/components/portfolio/PortfolioHoldings', () => ({ default: () => null }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => <button type="button">add-tx</button> }));
vi.mock('@/components/portfolio/PortfolioTransactions', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioAllocation', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioScores', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioTearsheet', () => ({ default: () => null }));
vi.mock('@/components/portfolio/RefreshPortfolioButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioForecast', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioDividends', () => ({ default: () => null }));

import PortfolioTabs from '@/components/portfolio/PortfolioTabs';
import TaxesView from '@/components/taxes/TaxesView';

async function headingOrder(node: Element) {
    const result = await axe.run(node, { runOnly: { type: 'rule', values: ['heading-order'] } });
    return result.violations.flatMap((v) => v.nodes.map((n) => n.html));
}
const levels = (node: Element) =>
    Array.from(node.querySelectorAll('h1,h2,h3,h4,h5,h6')).map((h) => `${h.tagName.toLowerCase()} ${h.textContent?.trim()}`);

describe('a11y: titulares sin saltos de nivel (heading-order)', () => {
    it('/portfolio: «Valor de la cartera» es h2 bajo el h1 «Resumen»', async () => {
        const summary = {
            totalValue: 10000, totalCost: 8000, totalGain: 2000, totalGainPercent: 25, baseCurrency: 'EUR', cash: 0,
            holdings: [{ symbol: 'A', cost: 8000, value: 10000, gain: 2000, gainPercent: 25 }], quality: undefined,
        };
        const { container } = render(
            <PortfolioTabs summary={summary as never} transactions={[]} scores={{} as never} tearsheet={null}
                forecast={null} dividends={null} userId="u" />,
        );
        expect(levels(container)).toContain('h2 Valor de la cartera');
        expect(await headingOrder(container)).toEqual([]);
    });

    it('/taxes: «Informe fiscal» y «Posiciones Fiscales» son h2 bajo el h1 «Impuestos»', async () => {
        const { container } = render(
            <main>
                <h1>Impuestos</h1>
                <TaxesView initialHoldings={[]} initialReport={null} initialThresholds720={null} initialFile720={null} year={2026} />
            </main>,
        );
        const found = levels(container);
        expect(found).toContain('h2 Informe fiscal 2026');
        expect(found).toContain('h2 Posiciones Fiscales');
        expect(await headingOrder(container)).toEqual([]);
    });
});
