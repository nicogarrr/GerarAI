import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { formatMoney } from '@/lib/format';
import type { DemoValuation } from '@/lib/market/demo-valuation';
import {
    ManualDemoPanel,
    type ManualDemoPanelProps,
} from '@/components/paper-trading/ManualDemoPanel';
import type {
    DemoPositionView,
    DemoStateView,
    HistoryPageResult,
    HistoryRow,
    SubmitFill,
    SubmitFx,
} from '@/components/paper-trading/submit';

const mocks = vi.hoisted(() => ({
    refresh: vi.fn(),
    searchStocksWithStatus: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: (q: string) => mocks.searchStocksWithStatus(q),
}));

// jsdom no implementa matchMedia y Panel lo usa (useMediaQuery).
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
    window.matchMedia = ((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
}

function accountView(over: Partial<DemoStateView> = {}): DemoStateView {
    return { cashEUR: 100_000, cashUSD: 0, realizedEUR: 0, realizedUSD: 0, positions: [], violations: [], notices: [], ...over };
}
function position(over: Partial<DemoPositionView> = {}): DemoPositionView {
    return {
        instrumentKey: 'A:ASTS', name: 'AST SpaceMobile', kind: 'accion', currency: 'USD',
        quantity: 10, avgCost: 40, realizedPnl: 0, optionExpiry: null, optionBadge: null, ...over,
    };
}
function valuationFor(pos: DemoPositionView): DemoValuation {
    return {
        rows: [{
            instrumentKey: pos.instrumentKey, name: pos.name, kind: pos.kind, currency: pos.currency,
            quantity: pos.quantity, avgCost: pos.avgCost, status: 'valorada', price: 50,
            marketValue: pos.quantity * 50, unrealizedPnl: pos.quantity * 10, unrealizedPct: 25,
            currencyBasis: 'finnhub-listado', quoteLabel: null, note: null,
        }],
        totals: [{
            currency: pos.currency, marketValue: pos.quantity * 50, unrealizedPnl: pos.quantity * 10,
            costBasis: pos.quantity * pos.avgCost, valuedPositions: 1,
        }],
        coverage: { valued: 1, total: 1 },
    };
}
let rowSeq = 0;
function historyRow(over: Partial<HistoryRow> = {}): HistoryRow {
    rowSeq += 1;
    return {
        clientOrderId: `row-${rowSeq}`, kind: 'accion', symbol: 'ASTS', name: 'AST SpaceMobile',
        side: 'buy', openClose: 'open', quantity: 10, status: 'filled', fillPrice: 40,
        currency: 'USD', fee: 0, executedAt: 1_700_000_000_000 + rowSeq * 1000,
        rejectReason: null, createdAt: 1_700_000_000_000 + rowSeq * 1000, simulated: true, ...over,
    };
}

function setup(over: Partial<ManualDemoPanelProps> = {}) {
    const submitFill = vi.fn<SubmitFill>();
    const submitFx = vi.fn<SubmitFx>();
    const utils = render(
        <ManualDemoPanel account={accountView()} ledger={[]} submitFill={submitFill} submitFx={submitFx} {...over} />,
    );
    return { submitFill, submitFx, ...utils };
}
function openTab(name: string) {
    fireEvent.mouseDown(screen.getByRole('tab', { name }));
}
async function flush() {
    await act(async () => {});
}
/** Localizador tolerante a texto partido en varios nodos (JSX con interpolaciones). */
function byTextContent(tag: string, fragment: string | RegExp) {
    return screen.getByText((_, el) => {
        if (!el || el.tagName !== tag) return false;
        const text = el.textContent ?? '';
        return typeof fragment === 'string' ? text.includes(fragment) : fragment.test(text);
    });
}

describe('ManualDemoPanel (cuenta demo manual)', () => {
    beforeEach(() => {
        mocks.refresh.mockClear();
        mocks.searchStocksWithStatus.mockReset();
    });
    afterEach(() => {
        vi.useRealTimers();
    });

    it('se etiqueta como cuenta de práctica con saldo ficticio, sin conexión con un broker', () => {
        setup();
        expect(screen.getByText(/Cuenta de práctica con saldo ficticio/)).toBeInTheDocument();
        expect(screen.getByText(/no es una ejecución de mercado ni hay conexión con un broker/)).toBeInTheDocument();
    });

    it('sin cuenta conectada los tickets quedan deshabilitados y se explica por qué', () => {
        setup({ account: null });
        expect(screen.getByRole('button', { name: 'Registrar compra simulada' })).toBeDisabled();
        expect(screen.getByText(/El registro en servidor todavía no está conectado/)).toBeInTheDocument();
        openTab('Divisas');
        expect(screen.getByRole('button', { name: 'Registrar conversión simulada' })).toBeDisabled();
        expect(screen.getByText(/El registro en servidor todavía no está conectado/)).toBeInTheDocument();
    });

    it('con cuenta muestra los saldos y cada pestaña su panel', () => {
        setup();
        expect(screen.getByText('Efectivo EUR')).toBeInTheDocument();
        expect(screen.getByText(/100\.000,00/)).toBeInTheDocument();
        expect(screen.getByText('Registrar operación')).toBeInTheDocument();
        openTab('Divisas');
        expect(screen.getByText(/Conversión EUR/)).toBeInTheDocument();
        openTab('Posiciones');
        expect(screen.getByText('Sin posiciones abiertas')).toBeInTheDocument();
        openTab('Historial');
        expect(screen.getByText('Sin operaciones registradas')).toBeInTheDocument();
    });

    it('las incidencias de integridad de la cuenta nunca se ocultan', () => {
        setup({ account: accountView({ violations: ['doc x: sobreventa detectada'] }) });
        expect(screen.getByRole('alert')).toHaveTextContent('doc x: sobreventa detectada');
    });

    it('el historial pinta fills y rechazos, y un rechazo nunca parece un fill', () => {
        setup({
            ledger: [
                historyRow({ clientOrderId: 'f1' }),
                historyRow({ clientOrderId: 'r1', status: 'rejected', fillPrice: null, executedAt: null, rejectReason: 'fondos insuficientes' }),
            ],
        });
        openTab('Historial');
        expect(screen.getByText('Manual simulada')).toBeInTheDocument();
        expect(screen.getByText('Rechazada')).toBeInTheDocument();
        expect(screen.getByText(/fondos insuficientes/)).toBeInTheDocument();
        expect(screen.getByText('N/D')).toBeInTheDocument();
        expect(screen.getByText(formatMoney(40, 'USD'))).toBeInTheDocument();
    });

    it('cargar más pide la página siguiente con el cursor y acumula sin duplicar filas', async () => {
        const first = historyRow({ clientOrderId: 'a' });
        const loadMoreHistory = vi.fn<(before: string) => Promise<HistoryPageResult>>().mockResolvedValue({
            ok: true,
            orders: [historyRow({ clientOrderId: 'a' }), historyRow({ clientOrderId: 'b', symbol: 'BMW', name: 'BMW' })],
            hasMore: false,
            nextBefore: null,
        });
        const { container } = setup({ ledger: [first], historyHasMore: true, historyNextBefore: 'cur-1', loadMoreHistory });
        openTab('Historial');
        fireEvent.click(screen.getByRole('button', { name: 'Cargar más' }));
        await flush();
        expect(loadMoreHistory).toHaveBeenCalledWith('cur-1');
        expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
        expect(screen.getByText('BMW')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Cargar más' })).toBeNull();
    });

    it('si cargar más falla se avisa y se conserva lo cargado', async () => {
        const loadMoreHistory = vi.fn<(before: string) => Promise<HistoryPageResult>>().mockResolvedValue({
            ok: false, message: 'sin conexión',
        });
        setup({ ledger: [historyRow({ clientOrderId: 'a' })], historyHasMore: true, historyNextBefore: 'cur-1', loadMoreHistory });
        openTab('Historial');
        fireEvent.click(screen.getByRole('button', { name: 'Cargar más' }));
        await flush();
        expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar más historial: sin conexión');
        expect(screen.getByText('ASTS')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Cargar más' })).toBeInTheDocument();
    });

    it('una primera página nueva del servidor descarta las páginas extra cargadas', async () => {
        const loadMoreHistory = vi.fn<(before: string) => Promise<HistoryPageResult>>().mockResolvedValue({
            ok: true,
            orders: [historyRow({ clientOrderId: 'b', symbol: 'BMW', name: 'BMW' })],
            hasMore: true,
            nextBefore: 'cur-2',
        });
        const { rerender, container } = setup({ ledger: [historyRow({ clientOrderId: 'a' })], historyHasMore: true, historyNextBefore: 'cur-1', loadMoreHistory });
        openTab('Historial');
        fireEvent.click(screen.getByRole('button', { name: 'Cargar más' }));
        await flush();
        expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
        const submitFill = vi.fn<SubmitFill>();
        const submitFx = vi.fn<SubmitFx>();
        rerender(
            <ManualDemoPanel
                account={accountView()}
                ledger={[historyRow({ clientOrderId: 'c', symbol: 'NVDA', name: 'NVIDIA' })]}
                historyHasMore={true}
                historyNextBefore="cur-9"
                loadMoreHistory={loadMoreHistory}
                submitFill={submitFill}
                submitFx={submitFx}
            />,
        );
        expect(container.querySelectorAll('tbody tr')).toHaveLength(1);
        expect(screen.getByText('NVDA')).toBeInTheDocument();
        expect(screen.queryByText('BMW')).toBeNull();
    });

    it('valoración al día muestra cobertura, totales por divisa y hora de consulta', () => {
        const pos = position();
        const asOf = Date.UTC(2026, 9, 27, 16, 30);
        setup({ account: accountView({ positions: [pos] }), valuation: valuationFor(pos), valuationAsOf: asOf });
        openTab('Posiciones');
        expect(byTextContent('P', /^Valoradas 1 de 1 posición con cotización del proveedor\./)).toBeInTheDocument();
        expect(byTextContent('LI', `USD: valor ${formatMoney(500, 'USD')}`)).toBeInTheDocument();
        const asOfFormat = new Intl.DateTimeFormat('es-ES', { timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
        expect(document.body.textContent).toContain(`consultado a las ${asOfFormat.format(new Date(asOf))} (hora de Madrid)`);
        expect(screen.getByText(/Las opciones no se valoran/)).toBeInTheDocument();
    });

    it('sin acción de refresco no se ofrece el botón de actualizar', () => {
        const pos = position();
        setup({ account: accountView({ positions: [pos] }), valuation: valuationFor(pos) });
        openTab('Posiciones');
        expect(screen.queryByRole('button', { name: /cotizaciones/ })).toBeNull();
    });

    it('si las posiciones cambiaron desde la última valoración, la valoración se oculta hasta reconsultar', () => {
        const pos = position({ quantity: 20 });
        setup({
            account: accountView({ positions: [pos] }),
            valuation: valuationFor(position({ quantity: 10 })),
            refreshValuation: vi.fn(),
        });
        openTab('Posiciones');
        expect(screen.getByText(/Sin actualizar: las posiciones han cambiado/)).toBeInTheDocument();
        expect(screen.queryByText(/Valoradas 1 de 1/)).toBeNull();
        expect(screen.getByRole('button', { name: 'Consultar cotizaciones' })).toBeInTheDocument();
    });

    it('el botón consultar trae la valoración; un fallo después se muestra sin borrarla', async () => {
        const pos = position();
        const refreshValuation = vi.fn<NonNullable<ManualDemoPanelProps['refreshValuation']>>()
            .mockResolvedValue({ ok: true, valuation: valuationFor(pos), asOf: 1_761_600_000_000, listingUnavailable: false, quoteFetchFailed: false, retryAfterSeconds: null });
        setup({ account: accountView({ positions: [pos] }), refreshValuation });
        openTab('Posiciones');
        expect(screen.getByText(/Valoración no disponible todavía/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Consultar cotizaciones' }));
        await flush();
        expect(byTextContent('P', /^Valoradas 1 de 1 posición/)).toBeInTheDocument();
        refreshValuation.mockResolvedValue({ ok: false, error: 'cuota agotada' });
        fireEvent.click(screen.getByRole('button', { name: 'Actualizar cotizaciones' }));
        await flush();
        expect(screen.getByRole('alert')).toHaveTextContent('No se pudieron actualizar las cotizaciones: cuota agotada');
        expect(byTextContent('P', /^Valoradas 1 de 1 posición/)).toBeInTheDocument();
    });

    it('reconsulta sola cada 60 s con la pestaña visible y posiciones, con backoff exponencial tras fallos', async () => {
        vi.useFakeTimers();
        const refreshValuation = vi.fn<NonNullable<ManualDemoPanelProps['refreshValuation']>>()
            .mockResolvedValue({ ok: false, error: 'caído' });
        setup({ account: accountView({ positions: [position()] }), refreshValuation });
        expect(refreshValuation).not.toHaveBeenCalled();
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(refreshValuation).toHaveBeenCalledTimes(1);
        // Tras el fallo la espera se dobla (120 s): a los 120 s de reloj aún no toca.
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(refreshValuation).toHaveBeenCalledTimes(1);
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(refreshValuation).toHaveBeenCalledTimes(2);
    });

    it('un resultado ok con todas las cotizaciones fallidas también arma el backoff', async () => {
        vi.useFakeTimers();
        const refreshValuation = vi.fn<NonNullable<ManualDemoPanelProps['refreshValuation']>>()
            .mockResolvedValue({ ok: true, valuation: valuationFor(position()), asOf: 1, listingUnavailable: false, quoteFetchFailed: true, retryAfterSeconds: null });
        setup({ account: accountView({ positions: [position()] }), refreshValuation });
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(refreshValuation).toHaveBeenCalledTimes(1);
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(refreshValuation).toHaveBeenCalledTimes(1);
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(refreshValuation).toHaveBeenCalledTimes(2);
    });

    it('sin posiciones abiertas no reconsulta sola', async () => {
        vi.useFakeTimers();
        const refreshValuation = vi.fn<NonNullable<ManualDemoPanelProps['refreshValuation']>>();
        setup({ account: accountView({ positions: [] }), refreshValuation });
        await act(async () => { await vi.advanceTimersByTimeAsync(3 * 60_000); });
        expect(refreshValuation).not.toHaveBeenCalled();
    });

    it('con la pestaña oculta no reconsulta', async () => {
        vi.useFakeTimers();
        vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
        const refreshValuation = vi.fn<NonNullable<ManualDemoPanelProps['refreshValuation']>>();
        setup({ account: accountView({ positions: [position()] }), refreshValuation });
        await act(async () => { await vi.advanceTimersByTimeAsync(3 * 60_000); });
        expect(refreshValuation).not.toHaveBeenCalled();
    });
});
