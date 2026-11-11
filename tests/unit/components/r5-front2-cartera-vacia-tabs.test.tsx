import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ComponentProps, ComponentType } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';

type LazyComponent = ComponentType<Record<string, unknown>>;

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), path: '/portfolio' }));
vi.mock('next/navigation', () => ({
    useSearchParams: () => nav.params, usePathname: () => nav.path, useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock('next/dynamic', () => ({
    // Respeta el loader: cada vista diferida renderiza su módulo (mockeado
    // abajo) una vez resuelta la promesa. El gráfico NAV (ssr: false) sigue
    // sustituido por un stub ligero con los props que asertan los tests.
    default: (loader: () => Promise<{ default: LazyComponent }>, opts?: { ssr?: boolean }) => {
        if (opts?.ssr === false) {
            const NavChartStub = (props: { data: unknown[]; positive: boolean; currency: string }) =>
                <div data-testid="nav-chart" data-points={props.data.length} data-positive={String(props.positive)} data-currency={props.currency} />;
            NavChartStub.displayName = "NavChartStub";
            return NavChartStub;
        }
        let Comp: LazyComponent | null = null;
        void loader().then((mod) => { Comp = mod.default; });
        return function LazyStub(props: Record<string, unknown>) {
            return Comp ? <Comp {...props} /> : null;
        };
    },
}));
vi.mock('@/components/portfolio/PortfolioDataNotice', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioSummary', () => ({ default: () => <div>summary</div> }));
vi.mock('@/components/portfolio/PortfolioHoldings', () => ({ default: () => <div>holdings-tab</div> }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => <button>add-tx</button> }));
vi.mock('@/components/portfolio/PortfolioTransactions', () => ({ default: () => <div>transactions-tab</div> }));
vi.mock('@/components/portfolio/PortfolioAllocation', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioScores', () => ({ default: () => <div>scores-tab</div> }));
vi.mock('@/components/portfolio/PortfolioTearsheet', () => ({ default: () => null }));
vi.mock('@/components/portfolio/RefreshPortfolioButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/PortfolioForecast', () => ({ default: () => <div>forecast-tab</div> }));
vi.mock('@/components/portfolio/PortfolioDividends', () => ({ default: () => <div>dividends-tab</div> }));
// SavingsProjection tira de plan.actions -> auth -> mongoose/nodemailer. Los
// loaders del mock de next/dynamic se disparan al evaluar el módulo
// (fire-and-forget): si ese grafo sigue importándose cuando el archivo
// termina, Vitest reporta EnvironmentTeardownError como error no manejado y
// la run falla aunque los tests pasen (visto en CI, #3992/#3995).
vi.mock('@/components/portfolio/SavingsProjection', () => ({ default: () => <div>savings-tab</div> }));
import PortfolioTabs from '@/components/portfolio/PortfolioTabs';

type TabsProps = ComponentProps<typeof PortfolioTabs>;

function summary(over: Record<string, unknown> = {}): TabsProps['summary'] {
    return { totalValue: 10000, totalCost: 8000, totalGain: 2000, totalGainPercent: 25, baseCurrency: 'EUR', cash: 0,
        holdings: [{ symbol: 'A', cost: 8000, value: 10000, gain: 2000, gainPercent: 25 }], quality: undefined, ...over } as TabsProps['summary'];
}
function renderTabs(over: Record<string, unknown> = {}) {
    return render(<PortfolioTabs summary={summary()} transactions={[]} scores={{} as TabsProps['scores']} tearsheet={null}
        forecast={null} dividends={null} userId="u" {...(over as Partial<TabsProps>)} />);
}

// Cartera vacía (sin posiciones ni caja): las tarjetas de arriba decían «N/D» y la tarjeta
// principal «Valor de la cartera 0,00 €». Un solo estado vacío en toda la página.
const blank = { holdings: [], totalValue: 0, totalCost: 0, totalGain: 0, totalGainPercent: 0, equityValue: 0, cash: 0 };

describe('cartera vacía: un solo estado vacío', () => {
    it('la tarjeta principal no pinta «0,00 €» cuando las de arriba dicen N/D', () => {
        renderTabs({ summary: summary(blank) });
        expect(screen.getByText(/Aún no tienes posiciones/)).toBeInTheDocument();
        expect(screen.queryByText(/0,00\s€/)).not.toBeInTheDocument();
    });
    it('sin posiciones pero con caja, el valor (la caja) sí es un dato', () => {
        renderTabs({ summary: summary({ ...blank, totalValue: 500, cash: 500 }) });
        expect(screen.getByText(/500,00\s€/)).toBeInTheDocument();
    });
    it('con posiciones, el valor sigue ahí', () => {
        renderTabs();
        expect(screen.getByText(/10\.000,00\s€/)).toBeInTheDocument();
    });
});
