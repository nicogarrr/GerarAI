import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

// Rendimiento de «Resumen»: cambiar el periodo del gráfico (1S/1M/3M/…) solo
// cambia el panel del gráfico. Las métricas, el donut y el tearsheet no
// dependen del periodo y no deben volver a pintarse (antes se repintaba todo
// «Resumen» en cada clic: 11–14 ms frente a 4–5 ms en el banco, 60 posiciones).
const h = vi.hoisted(() => ({ summary: vi.fn(), notice: vi.fn(), allocation: vi.fn(), tearsheet: vi.fn(), chart: vi.fn() }));
vi.mock('next/navigation', () => ({
    useSearchParams: () => new URLSearchParams(), usePathname: () => '/portfolio', useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock('next/dynamic', () => ({
    default: (_loader: unknown, opts?: { ssr?: boolean }) => {
        if (opts?.ssr === false) {
            const NavChartStub = (props: { data: unknown[] }) => { h.chart(props.data.length); return <div data-testid="nav-chart" data-points={props.data.length} />; };
            return NavChartStub;
        }
        return function LazyStub() { return null; };
    },
}));
vi.mock('@/components/portfolio/PortfolioDataNotice', () => ({ default: () => { h.notice(); return null; } }));
vi.mock('@/components/portfolio/PortfolioSummary', () => ({ default: () => { h.summary(); return <div>summary</div>; } }));
vi.mock('@/components/portfolio/PortfolioAllocation', () => ({ default: () => { h.allocation(); return null; } }));
vi.mock('@/components/portfolio/PortfolioTearsheet', () => ({ default: () => { h.tearsheet(); return null; } }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/RefreshPortfolioButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/SavingsProjection', () => ({ default: () => null }));
import PortfolioTabs from '@/components/portfolio/PortfolioTabs';

const dates: string[] = [];
const nav: number[] = [];
for (let i = 0; i < 500; i++) {
    dates.push(new Date(Date.parse('2025-01-02') + i * 86400000).toISOString().slice(0, 10));
    nav.push(100 + i * 0.1);
}
const summary = { totalValue: 10000, totalCost: 8000, totalGain: 2000, totalGainPercent: 25, baseCurrency: 'EUR', cash: 0,
    holdings: [{ symbol: 'A', cost: 8000, value: 10000, gain: 2000, gainPercent: 25 }], quality: undefined } as any;
const scores = { quality: null, growth: null, value: null, dividend: null, cagr3y: null, history: { dates, nav } } as any;
const counts = () => [h.summary, h.notice, h.allocation, h.tearsheet].map((fn) => fn.mock.calls.length);

describe('Resumen: cambiar el periodo del gráfico', () => {
    it('solo repinta el gráfico, no las métricas, el donut ni el tearsheet', () => {
        render(<PortfolioTabs summary={summary} transactions={[]} scores={scores} tearsheet={null} forecast={null} dividends={null} userId="u" />);
        expect(counts()).toEqual([1, 1, 1, 1]);
        const before = Number(screen.getByTestId('nav-chart').dataset.points);
        fireEvent.click(within(screen.getByRole('group')).getByRole('button', { name: '1A' }));
        fireEvent.click(within(screen.getByRole('group')).getByRole('button', { name: '3M' }));
        expect(Number(screen.getByTestId('nav-chart').dataset.points)).not.toBe(before);
        expect(within(screen.getByRole('group')).getByRole('button', { name: '3M' })).toHaveAttribute('aria-pressed', 'true');
        expect(counts()).toEqual([1, 1, 1, 1]);
    });

    it('un resumen nuevo (refresco de datos) sí repinta métricas y donut', () => {
        const { rerender } = render(<PortfolioTabs summary={summary} transactions={[]} scores={scores} tearsheet={null} forecast={null} dividends={null} userId="u" />);
        rerender(<PortfolioTabs summary={{ ...summary, holdings: [...summary.holdings] }} transactions={[]} scores={scores} tearsheet={null} forecast={null} dividends={null} userId="u" />);
        expect(counts()).toEqual([2, 2, 2, 1]);
    });
});
