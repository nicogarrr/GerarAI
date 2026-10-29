import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, renderHook, screen, waitFor } from '@testing-library/react';

const h = vi.hoisted(() => ({ getSignals: vi.fn() }));
vi.mock('@/lib/actions/holding-signals.actions', () => ({ getHoldingSignals: h.getSignals }));
vi.mock('next/dynamic', () => ({
    default: () => (props: { chartData: unknown[]; currency?: string }) =>
        <div data-testid="donut" data-n={props.chartData.length} data-currency={props.currency ?? ''} />,
}));
import PortfolioDataNotice from '@/components/portfolio/PortfolioDataNotice';
import PortfolioAllocation from '@/components/portfolio/PortfolioAllocation';
import { AllocationTooltip } from '@/components/portfolio/AllocationTooltip';
import { DcaLevelChip, FairValueLine, useHoldingSignals } from '@/components/portfolio/HoldingSignals';

beforeEach(() => vi.clearAllMocks());

const quality = (over: Record<string, unknown> = {}): any => ({
    status: 'ok', positions: 3, missing_cost_positions: 0, position_dates: ['2026-10-01'], cash_dates: ['2026-10-01'],
    position_sources: [], cash_sources: [], cash_native: { EUR: 100, USD: -50 }, snapshots: 10, complete_snapshots: 8,
    return_observations: 5, latest_snapshot_date: null, latest_pricing_coverage: null, reasons: [], ...over,
});

describe('PortfolioDataNotice', () => {
    it('sin calidad o sin cartera no pinta nada', () => {
        const a = render(<PortfolioDataNotice quality={null} />);
        expect(a.container).toBeEmptyDOMElement();
        const b = render(<PortfolioDataNotice quality={quality({ status: 'no_portfolio' })} />);
        expect(b.container).toBeEmptyDOMElement();
    });

    it('fechas ausentes se declaran, no se dejan en blanco', () => {
        render(<PortfolioDataNotice quality={quality({ position_dates: [], cash_dates: [] })} />);
        const note = screen.getByRole('note');
        expect(note.textContent).toContain('posiciones a fecha no disponible');
        expect(note.textContent).toContain('caja a fecha no disponible');
    });

    it('falta de coste: avisa y dice que no se sustituye por ceros; IBKR explica por que', () => {
        const { unmount } = render(<PortfolioDataNotice quality={quality({ missing_cost_positions: 2 })} />);
        expect(screen.getByText(/Falta una base de coste válida en 2 posiciones/)).toBeInTheDocument();
        expect(screen.getByText(/No se sustituyen por ceros ni estimaciones/)).toBeInTheDocument();
        expect(screen.queryByText(/IBKR no entrega/)).not.toBeInTheDocument();
        unmount();
        render(<PortfolioDataNotice quality={quality({ missing_cost_positions: 1, position_sources: ['ibkr_flex'] })} />);
        expect(screen.getByText(/IBKR no entrega/)).toBeInTheDocument();
    });

    it('fechas en detalle cerrado; conserva el aviso por captura de pantalla', () => {
        render(<PortfolioDataNotice quality={quality({ reasons: ['mixed_valuation_dates'], position_sources: ['screenshot_confirmed'] })} />);
        expect(screen.queryByText(/no es una foto conciliada del mismo día/)).not.toBeInTheDocument();
        const details = screen.getByText(/Datos de cartera: posiciones a/).closest('details');
        expect(details).not.toBeNull();
        expect(details).not.toHaveAttribute('open');
        expect(screen.getByText(/posiciones importadas desde una captura/)).toBeInTheDocument();
    });

    it('sin incidencias no hay avisos ambar; saldo negativo se conserva como deuda', () => {
        render(<PortfolioDataNotice quality={quality()} />);
        expect(screen.queryByText(/Falta una base de coste/)).not.toBeInTheDocument();
        expect(screen.queryByText(/foto conciliada/)).not.toBeInTheDocument();
        const note = screen.getByRole('note').textContent!;
        expect(note).toMatch(/-\$?50/);
        expect(note).toContain('deuda de margen');
        expect(note).toContain('10 fotos guardadas, 8 con cobertura');
    });
});

const holding = (symbol: string, value: number, extra: Record<string, unknown> = {}): any => ({
    symbol, value, cost: value, gain: 0, gainPercent: 0, valueMissing: false, fxMissing: false, ...extra,
});

describe('PortfolioAllocation', () => {
    it('vacia: invita a anadir posiciones', () => {
        render(<PortfolioAllocation holdings={[]} />);
        expect(screen.getByText('Añade posiciones para ver la distribución')).toBeInTheDocument();
    });

    it('pesos suman 100 entre las valoradas; sin valor o valoración suspendida queda fuera y se avisa', () => {
        render(<PortfolioAllocation holdings={[holding('AAA', 300), holding('BBB', 100), holding('CCC', 0, { valueMissing: true }), holding('DDD', 50, { valuationHold: { reason: 'suspensión', effectiveDate: '2026-10-01' } })]} baseCurrency="EUR" />);
        const legend = document.getElementById('portfolio-allocation-legend')!;
        expect(legend.textContent).toMatch(/AAA.*75,0\s?%/);
        expect(legend.textContent).toMatch(/BBB.*25,0\s?%/);
        expect(legend.textContent).not.toContain('CCC');
        expect(legend.textContent).not.toContain('DDD');
        expect(screen.getByText(/Distribución incompleta: 2 posiciones sin valor/)).toBeInTheDocument();
        expect(screen.getByTestId('donut')).toHaveAttribute('data-currency', 'EUR');
        expect(screen.getByText('Posiciones').previousSibling!.textContent).toBe('2');
    });

    it('coste pendiente de conciliación (fxMissing) NO excluye del donut: pesos sobre valor de mercado', () => {
        // Estado real de prod 2026-10-29: base de coste IBKR pendiente en toda
        // la cartera; el donut decía «ninguna posición tiene valor disponible»
        // con el valor bruto a la vista.
        render(<PortfolioAllocation holdings={[holding('AAA', 300, { cost: 0, fxMissing: true }), holding('BBB', 100, { cost: 0, fxMissing: true })]} />);
        const legend = document.getElementById('portfolio-allocation-legend')!;
        expect(legend.textContent).toMatch(/AAA.*75,0\s?%/);
        expect(legend.textContent).toMatch(/BBB.*25,0\s?%/);
        expect(screen.queryByText(/Distribución N\/D/)).not.toBeInTheDocument();
        expect(screen.queryByText(/sin valor/)).not.toBeInTheDocument();
        expect(screen.getByText('Pesos sobre el valor bruto de las posiciones')).toBeInTheDocument();
    });

    it('una sola sin valor: singular', () => {
        render(<PortfolioAllocation holdings={[holding('AAA', 10), holding('CCC', 0, { valueMissing: true })]} />);
        expect(screen.getByText(/1 posición sin valor/)).toBeInTheDocument();
    });

    it('ninguna valorada: N/D, sin donut ni contador falso', () => {
        render(<PortfolioAllocation holdings={[holding('CCC', 0, { valueMissing: true })]} />);
        expect(screen.getByText(/Distribución N\/D/)).toBeInTheDocument();
        expect(screen.queryByTestId('donut')).not.toBeInTheDocument();
        expect(screen.queryByText('Posiciones')).not.toBeInTheDocument();
    });

    it('caja negativa se muestra como margen en rojo y fuera del donut', () => {
        render(<PortfolioAllocation holdings={[holding('AAA', 100)]} cash={-2500} baseCurrency="EUR" />);
        const label = screen.getByText('Caja (margen)');
        expect(label).toBeInTheDocument();
        const row = label.parentElement!;
        expect(row.textContent).toMatch(/-\s?2\.?500/);
        expect(row.querySelector('.text-red-400')).not.toBeNull();
        expect(screen.getByTestId('donut')).toHaveAttribute('data-n', '1');
    });

    it('caja positiva y caja 0', () => {
        const { unmount } = render(<PortfolioAllocation holdings={[holding('AAA', 100)]} cash={500} />);
        expect(screen.getByText('Caja')).toBeInTheDocument();
        unmount();
        render(<PortfolioAllocation holdings={[holding('AAA', 100)]} cash={0} />);
        expect(screen.queryByText('Caja')).not.toBeInTheDocument();
    });

    it('solo caja (sin posiciones) no cae en el estado vacio', () => {
        render(<PortfolioAllocation holdings={[]} cash={100} />);
        expect(screen.queryByText('Añade posiciones para ver la distribución')).not.toBeInTheDocument();
        expect(screen.getByText(/Distribución N\/D/)).toBeInTheDocument();
    });
});

describe('AllocationTooltip', () => {
    const slice = (symbol: string): any => ({ symbol, value: 1234.5, percentage: 12.34, gain: -5, gainPercent: -2.5, name: symbol });

    it('inactivo o sin payload: null', () => {
        expect(AllocationTooltip({ active: false, payload: [{ payload: slice('A') }] })).toBeNull();
        expect(AllocationTooltip({ active: true, payload: [] })).toBeNull();
        expect(AllocationTooltip({ active: true })).toBeNull();
    });

    it('posicion: enlace a su ficha, valor en la moneda base y G/P con signo', () => {
        render(<>{AllocationTooltip({ active: true, payload: [{ payload: slice('AAPL') }], currency: 'EUR' })}</>);
        expect(screen.getByRole('link', { name: 'AAPL' })).toHaveAttribute('href', '/research/AAPL');
        expect(document.body.textContent).toMatch(/1\.?234,50\s?€/);
        expect(document.body.textContent).toContain('12,3');
        expect(screen.getByText(/-2,50\s?%/).className).toContain('text-red');
    });

    it('caja: sin enlace ni G/P', () => {
        render(<>{AllocationTooltip({ active: true, payload: [{ payload: slice('Caja') }], currency: 'EUR' })}</>);
        expect(screen.queryByRole('link')).not.toBeInTheDocument();
        expect(screen.queryByText(/G\/P/)).not.toBeInTheDocument();
    });

    it('ganancia positiva en verde', () => {
        render(<>{AllocationTooltip({ active: true, payload: [{ payload: { ...slice('X'), gain: 5, gainPercent: 3 } }], currency: 'EUR' })}</>);
        expect(screen.getByText(/\+3,00\s?%/).className).toContain('text-green');
    });
});

describe('useHoldingSignals', () => {
    it('sin simbolos devuelve vacio sin llamar al backend', () => {
        const { result } = renderHook(() => useHoldingSignals([]));
        expect(result.current).toEqual({ fairValues: {}, dca: null });
        expect(h.getSignals).not.toHaveBeenCalled();
    });

    it('una sola peticion con simbolos unicos, mayusculas y ordenados', async () => {
        const value = { fairValues: {}, dca: {} };
        h.getSignals.mockResolvedValue(value);
        const { result } = renderHook(() => useHoldingSignals(['msft', 'AAPL', 'aapl']));
        expect(result.current).toBeNull();
        await waitFor(() => expect(result.current).toBe(value));
        expect(h.getSignals).toHaveBeenCalledTimes(1);
        expect(h.getSignals).toHaveBeenCalledWith(['AAPL', 'MSFT']);
    });

    it('si falla degrada a vacio, nunca lanza', async () => {
        h.getSignals.mockRejectedValue(new Error('x'));
        const { result } = renderHook(() => useHoldingSignals(['AAPL']));
        await waitFor(() => expect(result.current).toEqual({ fairValues: {}, dca: null }));
    });

    it('si cambian las posiciones no se pinta la lectura vieja', async () => {
        h.getSignals.mockResolvedValueOnce({ fairValues: {}, dca: {} });
        const { result, rerender } = renderHook(({ s }) => useHoldingSignals(s), { initialProps: { s: ['AAA'] } });
        await waitFor(() => expect(result.current).not.toBeNull());
        h.getSignals.mockReturnValueOnce(new Promise(() => {}));
        rerender({ s: ['BBB'] });
        expect(result.current).toBeNull();
    });
});

describe('DcaLevelChip y FairValueLine', () => {
    it('cargando: puntos suspensivos', () => {
        const a = render(<DcaLevelChip symbol="A" signals={null} />);
        expect(a.container.textContent).toBe('…');
        const b = render(<FairValueLine symbol="A" price={1} priceCurrency="USD" signals={null} />);
        expect(b.container.textContent).toBe('…');
    });

    it('motor DCA no disponible: Sin nivel con su explicacion', () => {
        render(<DcaLevelChip symbol="A" signals={{ fairValues: {}, dca: null }} />);
        expect(screen.getByText('Sin nivel')).toHaveAttribute('title', expect.stringContaining('aún no está activo'));
    });

    it('ticker sin nivel evaluado', () => {
        render(<DcaLevelChip symbol="A" signals={{ fairValues: {}, dca: {} }} />);
        expect(screen.getByText('Sin nivel')).toHaveAttribute('title', 'Este ticker aún no tiene nivel DCA evaluado.');
    });

    it('nivel provisional con color y mes en formacion', () => {
        render(<DcaLevelChip symbol="a" signals={{ fairValues: {}, dca: { A: { level: 2, label: '2X DCA', forming: true, signalDate: '2026-09-30', color: 'rgb(1, 2, 3)', fg: 'rgb(4, 5, 6)' } } }} />);
        const chip = screen.getByText('2X DCA (provisional)');
        expect(chip).toHaveStyle({ backgroundColor: 'rgb(1, 2, 3)', color: 'rgb(4, 5, 6)' });
        expect(chip.getAttribute('title')).toContain('cierre');
    });

    it('sin valor justo: lo dice', () => {
        render(<FairValueLine symbol="A" price={10} priceCurrency="USD" signals={{ fairValues: {}, dca: null }} />);
        expect(screen.getByText('Sin valor justo')).toBeInTheDocument();
    });

    const fair = (over = {}): any => ({ value: 120, source: 'tesis', label: 'Tesis v3', asOf: '2026-10-01', currency: 'USD', publishable: true, ...over });

    it('margen frente al precio solo si la divisa coincide', () => {
        const { unmount } = render(<FairValueLine symbol="a" price={100} priceCurrency="usd" signals={{ fairValues: { A: fair() }, dca: null }} />);
        expect(screen.getByText(/\+20,0\s?%/).className).toContain('text-good');
        unmount();
        render(<FairValueLine symbol="A" price={100} priceCurrency="EUR" signals={{ fairValues: { A: fair() }, dca: null }} />);
        expect(screen.queryByText(/%/)).not.toBeInTheDocument();
        expect(screen.getByText('Tesis v3')).toBeInTheDocument();
    });

    it('precio por encima del valor justo: margen negativo', () => {
        render(<FairValueLine symbol="A" price={150} priceCurrency="USD" signals={{ fairValues: { A: fair() }, dca: null }} />);
        expect(screen.getByText(/-20,0\s?%/).className).toContain('text-bad');
    });

    it('divisa del valor justo invalida: numero sin simbolo inventado', () => {
        const { container } = render(<FairValueLine symbol="A" price={100} priceCurrency="USD" signals={{ fairValues: { A: fair({ currency: 'XXXXX' }) }, dca: null }} />);
        expect(container.textContent).toContain('120');
        expect(container.textContent).not.toContain('$');
    });
});
