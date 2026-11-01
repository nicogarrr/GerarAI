import { describe, expect, it, vi } from 'vitest';
import type { ComponentProps, ComponentType } from 'react';
import { act, render, screen } from '@testing-library/react';
import { LocaleProvider } from '@/lib/i18n/client';

// Con el idioma en inglés (Ajustes → Idioma), las pestañas de previsión y
// dividendos y el desglose 0588 deben pintarse en inglés, no en el español por
// defecto de los parámetros `ti`/`f`.

type LazyComponent = ComponentType<Record<string, unknown>>;

const nav = vi.hoisted(() => ({ params: new URLSearchParams({ tab: 'dividendos' }) }));
vi.mock('next/navigation', () => ({
    useSearchParams: () => nav.params, usePathname: () => '/portfolio', useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock('next/dynamic', () => ({
    default: (loader: () => Promise<{ default: LazyComponent }>, opts?: { ssr?: boolean }) => {
        if (opts?.ssr === false) return function Stub() { return null; };
        let Comp: LazyComponent | null = null;
        void loader().then((mod) => { Comp = mod.default; });
        return function LazyStub(props: Record<string, unknown>) { return Comp ? <Comp {...props} /> : null; };
    },
}));
type Ti = ((key: string) => string) | undefined;
vi.mock('@/components/portfolio/PortfolioDataNotice', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioSummary', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioHoldings', () => ({ default: () => null }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioTransactions', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioAllocation', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioScores', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioTearsheet', () => ({ default: () => null }));
vi.mock('@/components/portfolio/RefreshPortfolioButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioForecast', () => ({
    default: ({ ti }: { ti: Ti }) => <div>forecast:{ti ? ti('portfolio.holdings.title') : 'sin-idioma'}</div>,
}));
vi.mock('@/components/portfolio/PortfolioDividends', () => ({
    default: ({ ti }: { ti: Ti }) => <div>dividends:{ti ? ti('portfolio.holdings.title') : 'sin-idioma'}</div>,
}));
// Igual que en PortfolioTabs.test.tsx: SavingsProjection real importa
// plan.actions -> auth -> mongoose, y el loader fire-and-forget del mock de
// next/dynamic puede seguir resolviéndolo tras el teardown del archivo
// (EnvironmentTeardownError no manejado en CI).
vi.mock('@/components/portfolio/SavingsProjection', () => ({ default: () => null }));

import PortfolioTabs from '@/components/portfolio/PortfolioTabs';
import { FilingSection } from '@/components/taxes/FilingSections';
import { translateMessage } from '@/lib/i18n/translate';

type TabsProps = ComponentProps<typeof PortfolioTabs>;

const summary: TabsProps['summary'] = {
    totalValue: 1, totalCost: 1, totalGain: 0, totalGainPercent: 0, baseCurrency: 'EUR', cash: 0, holdings: [],
    equityValue: 1, status: 'ok', missingFx: [], valuationHold: [],
};
const holdingsEn = translateMessage('en', 'portfolio.holdings.title');

describe('cartera en inglés', () => {
    it.each([['dividendos', 'dividends'], ['prevision', 'forecast']])('?tab=%s recibe el idioma activo', async (tab, label) => {
        nav.params = new URLSearchParams({ tab });
        render(<LocaleProvider locale="en"><PortfolioTabs summary={summary} transactions={[]} scores={{} as TabsProps['scores']}
            tearsheet={null} forecast={{} as TabsProps['forecast']} dividends={{} as TabsProps['dividends']} userId="u" /></LocaleProvider>);
        await act(async () => {});
        expect(await screen.findByText(`${label}:${holdingsEn}`)).toBeInTheDocument();
    });

    it('desglose 0588 por país en inglés', () => {
        render(<LocaleProvider locale="en"><FilingSection year={2025} onPreview={() => {}} onReset={() => {}} filing={{
            available: true,
            casillas: { available: true, acciones_negociadas: { rows: [] }, dividendos: {} },
            double_taxation: { status: 'ok', total_deduction_base: 10, spanish_withholding_base: { amount: 0 },
                countries: [{ country: 'US', gross_base: 100, withheld_base: 15, treaty_rate: 0.15, treaty_cap_base: 15,
                    tme_limit_base: null, limit_applied: 'tope_convenio', deduction_base: 10 }] },
        }} /></LocaleProvider>);
        const list = screen.getByRole('list', { name: 'Box 0588 deduction by country' });
        expect(list.textContent).toMatch(/US: gross .*withheld .*gross × TME TME missing · deduction .*\(treaty cap applies\)/);
        expect(list.textContent).not.toMatch(/bruto|retenido|deducción/);
    });
});
