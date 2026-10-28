import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), path: '/portfolio' }));
vi.mock('next/navigation', () => ({
    useSearchParams: () => nav.params, usePathname: () => nav.path, useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock('next/dynamic', () => ({
    default: () => (props: { data: unknown[]; positive: boolean; currency: string }) =>
        <div data-testid="nav-chart" data-points={props.data.length} data-positive={String(props.positive)} data-currency={props.currency} />,
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
import PortfolioTabs from '@/components/portfolio/PortfolioTabs';

function summary(over: Record<string, unknown> = {}): any {
    return { totalValue: 10000, totalCost: 8000, totalGain: 2000, totalGainPercent: 25, baseCurrency: 'EUR', cash: 0,
        holdings: [{ symbol: 'A', cost: 8000, value: 10000, gain: 2000, gainPercent: 25 }], quality: undefined, ...over };
}
function renderTabs(over: Record<string, unknown> = {}) {
    return render(<PortfolioTabs summary={summary()} transactions={[]} scores={{} as any} tearsheet={null}
        forecast={null} dividends={null} userId="u" {...over as any} />);
}
const selected = () => screen.getAllByRole('tab').find((t) => t.getAttribute('aria-selected') === 'true')!.textContent;

beforeEach(() => { nav.params = new URLSearchParams(); nav.path = '/portfolio'; vi.restoreAllMocks(); });

describe('PortfolioTabs pestana desde la URL', () => {
    it.each([
        ['', 'Resumen'], ['posiciones', 'Posiciones'], ['movimientos', 'Movimientos'], ['dividendos', 'Dividendos'],
        ['prevision', 'Previsión'], ['estrategia', 'Factores'], ['factores', 'Factores'], ['inventada', 'Resumen'],
    ])('?tab=%s abre %s', (tab, label) => {
        if (tab) nav.params = new URLSearchParams({ tab });
        renderTabs();
        expect(selected()).toBe(label);
    });

    it('cambiar de pestana conserva los demas parametros en la URL', () => {
        nav.params = new URLSearchParams('foo=bar&page=2');
        const spy = vi.spyOn(window.history, 'replaceState');
        renderTabs();
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'Movimientos' }));
        expect(spy).toHaveBeenCalledWith(null, '', '/portfolio?foo=bar&page=2&tab=movimientos');
        expect(screen.getByText('transactions-tab')).toBeInTheDocument();
    });

    it('un cambio posterior del parametro de URL sincroniza la pestana', () => {
        const { rerender } = renderTabs();
        expect(selected()).toBe('Resumen');
        nav.params = new URLSearchParams({ tab: 'posiciones' });
        rerender(<PortfolioTabs summary={summary()} transactions={[]} scores={{} as any} tearsheet={null} forecast={null} dividends={null} userId="u" />);
        expect(selected()).toBe('Posiciones');
    });
});

describe('PortfolioTabs contenido', () => {
    it('previsión y dividendos no cargados: aviso, no un panel vacio', () => {
        nav.params = new URLSearchParams({ tab: 'prevision' });
        const { unmount } = renderTabs();
        expect(screen.getByRole('status')).toHaveTextContent('No se pudo cargar la previsión');
        unmount();
        nav.params = new URLSearchParams({ tab: 'dividendos' });
        renderTabs();
        expect(screen.getByRole('status')).toHaveTextContent('No se pudo cargar la proyección de dividendos');
    });

    it('con datos pinta los paneles', () => {
        nav.params = new URLSearchParams({ tab: 'prevision' });
        const { unmount } = renderTabs({ forecast: {} });
        expect(screen.getByText('forecast-tab')).toBeInTheDocument();
        unmount();
        nav.params = new URLSearchParams({ tab: 'dividendos' });
        renderTabs({ dividends: {} });
        expect(screen.getByText('dividends-tab')).toBeInTheDocument();
    });

    it('mensaje de cartera parcial solo si lo hay', () => {
        const { unmount } = renderTabs({ partialMessage: 'faltan precios' });
        expect(screen.getByText(/Cartera parcialmente disponible: faltan precios/)).toBeInTheDocument();
        unmount();
        renderTabs();
        expect(screen.queryByText(/Cartera parcialmente disponible/)).not.toBeInTheDocument();
    });

    it('cartera vacia: invita a registrar la primera compra y no muestra rentabilidad', () => {
        renderTabs({ summary: summary({ holdings: [], totalGain: 0, totalValue: 0 }) });
        expect(screen.getByText(/Aún no tienes posiciones/)).toBeInTheDocument();
        expect(screen.queryByText(/Rentabilidad no disponible/)).not.toBeInTheDocument();
    });

    it('sin base de coste valida: no presenta el valor neto como beneficio', () => {
        renderTabs({ summary: summary({ holdings: [{ symbol: 'A', cost: 0, value: 10000, gain: 10000, gainPercent: 0 }] }) });
        expect(screen.getByText(/Rentabilidad no disponible: falta una base de coste válida/)).toBeInTheDocument();
        expect(screen.queryByText(/\+25,00/)).not.toBeInTheDocument();
    });

    it('con base de coste: rentabilidad con signo y ganancia en euros', () => {
        renderTabs();
        const line = screen.getByText(/\+25,00\s?%/).closest('p')!;
        expect(line.textContent).toMatch(/2\.?000/);
        expect(line.className).toContain('text-green');
    });

    it('perdida: en rojo y sin mas', () => {
        renderTabs({ summary: summary({ totalGain: -500, totalGainPercent: -5 }) });
        const line = screen.getByText(/-5,00\s?%|−5,00\s?%/).closest('p')!;
        expect(line.className).toContain('text-red');
    });

    it('sin serie historica: no dibuja grafico y lo explica', () => {
        renderTabs();
        expect(screen.getByText(/Aún no hay una serie continua/)).toBeInTheDocument();
        expect(screen.queryByTestId('nav-chart')).not.toBeInTheDocument();
    });

    it('con serie: dibuja el grafico y el periodo cambia el numero de puntos', () => {
        const dates = Array.from({ length: 400 }, (_, i) => new Date(Date.UTC(2025, 8, 1) + i * 86400000).toISOString().slice(0, 10));
        const nav_ = dates.map((_, i) => 1000 + i);
        renderTabs({ scores: { history: { dates, nav: nav_ } } });
        const points = () => Number(screen.getByTestId('nav-chart').getAttribute('data-points'));
        const month = points();
        expect(month).toBeGreaterThan(0);
        fireEvent.click(screen.getByRole('button', { name: 'Todo' }));
        expect(points()).toBeGreaterThan(month);
        expect(screen.getByTestId('nav-chart')).toHaveAttribute('data-currency', 'EUR');
    });

    it('serie con fechas pero sin nav no dibuja', () => {
        renderTabs({ scores: { history: { dates: ['2026-01-01'], nav: [] } } });
        expect(screen.queryByTestId('nav-chart')).not.toBeInTheDocument();
    });
});
