import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProPick } from '@/lib/actions/proPicks.actions';

const { runWalkForwardBacktest, generateProPicksForStrategy } = vi.hoisted(() => ({
    runWalkForwardBacktest: vi.fn(),
    generateProPicksForStrategy: vi.fn(),
}));
vi.mock('@/lib/actions/propicks-backtest.actions', () => ({ runWalkForwardBacktest }));
vi.mock('@/lib/actions/proPicks.actions', () => ({ generateProPicksForStrategy }));

// Hijos pesados (cada uno con su propio test o sus propias server actions):
// aquí solo se comprueba lo que ProPicksTabs les pasa y cuándo los monta.
vi.mock('@/components/proPicks/EnhancedProPicksContent', () => ({
    default: (props: { initialPicks: ProPick[]; generatedAt?: string; initialPassedCount: number | null; onRunUpdated: (a: string | null) => void }) => (
        <div data-testid="picks">
            picks:{props.initialPicks.length} run:{props.generatedAt ?? 'none'} passed:{String(props.initialPassedCount)}
            <button onClick={() => props.onRunUpdated('2026-11-01')}>nuevo-run</button>
        </div>
    ),
}));
vi.mock('@/components/proPicks/GemsView', () => ({ default: () => <div>vista-joyas</div> }));
vi.mock('@/components/proPicks/PaperTradingView', () => ({ default: () => <div>vista-paper</div> }));
vi.mock('@/components/proPicks/TrackRecordView', () => ({ default: () => <div>vista-track-record</div> }));
vi.mock('@/components/proPicks/DcaBacktestPanel', () => ({ default: () => <div>panel-dca</div> }));
vi.mock('@/components/proPicks/WalkForwardResults', () => ({
    default: ({ result }: { result: { months: number } }) => <div>walk-forward:{result.months}</div>,
}));
vi.mock('@/components/proPicks/StrategySelector', () => ({
    default: (props: { currentStrategy: string; onStrategyChange: (id: string) => void }) => (
        <div>
            selector:{props.currentStrategy}
            <button onClick={() => props.onStrategyChange('value')}>elegir-value</button>
            <button onClick={() => props.onStrategyChange('momentum')}>elegir-momentum</button>
        </div>
    ),
}));
vi.mock('@/components/proPicks/StrategyFactsheet', () => ({
    default: (props: { strategyId: string; name: string; available: boolean }) => (
        <div>
            ficha:{props.strategyId}:{props.name}:{props.available ? 'disponible' : 'sin-datos'}
        </div>
    ),
}));
vi.mock('@/components/proPicks/MonthlyRebalanceView', () => ({
    default: (props: { currentPicks: ProPick[]; picksStatus: string; picksError: string | null; strategyId: string; strategyName?: string }) => (
        <div>
            rebalanceo:{props.strategyId}:{props.strategyName}:{props.picksStatus}:{props.currentPicks.map((p) => p.symbol).join(',')}:{props.picksError ?? ''}
        </div>
    ),
}));

import ProPicksTabs from '@/components/proPicks/ProPicksTabs';

const pick = (symbol: string, asOf = '2026-10-27'): ProPick =>
    ({ symbol, company: symbol, score: 80, grade: 'A', asOf, categoryScores: {}, reasons: [], confidenceReasons: [], confidence: 80, confidenceLevel: 'Alta', facts: {} }) as unknown as ProPick;

const strategies = [
    { id: 'adaptive', name: 'Adaptativa', description: 'd' },
    { id: 'value', name: 'Value', description: 'd' },
];

function openTab(name: string) {
    fireEvent.mouseDown(screen.getByRole('tab', { name }), { button: 0 });
}

beforeEach(() => {
    vi.clearAllMocks();
    runWalkForwardBacktest.mockResolvedValue({ months: 12 });
    generateProPicksForStrategy.mockResolvedValue([pick('AAPL')]);
});

describe('ProPicksTabs', () => {
    it('muestra las 8 pestañas y arranca en Selección IA con los datos del servidor', () => {
        render(<ProPicksTabs strategies={strategies} initialPicks={[pick('A'), pick('B')]} generatedAt="2026-10-27" passedCount={7} />);
        expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual([
            'Selección IA',
            'Joyas',
            'Valor profundo',
            'Estrategia y rebalanceo',
            'Backtest',
            'Resultados simulados de la IA',
            'Radar global',
            'Oportunidades DCA',
        ]);
        expect(screen.getByRole('tab', { name: 'Selección IA' })).toHaveAttribute('aria-selected', 'true');
        expect(screen.getByTestId('picks')).toHaveTextContent('picks:2 run:2026-10-27 passed:7');
        expect(runWalkForwardBacktest).not.toHaveBeenCalled();
        expect(generateProPicksForStrategy).not.toHaveBeenCalled();
    });

    it('Joyas solo monta GemsView al abrirla, y la selección sigue montada pero oculta', async () => {
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        expect(screen.queryByText('vista-joyas')).not.toBeInTheDocument();
        openTab('Joyas');
        expect(await screen.findByText('vista-joyas')).toBeInTheDocument();
        const picksPanel = screen.getByTestId('picks').parentElement as HTMLElement;
        expect(picksPanel).toBeInTheDocument();
        expect(picksPanel).toHaveAttribute('hidden');
    });

    it('Paper trading muestra su vista', async () => {
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        openTab('Resultados simulados de la IA');
        expect(await screen.findByText('vista-paper')).toBeInTheDocument();
    });

    it('La pestaña Backtest lanza el walk-forward una sola vez al abrirse y enseña el resultado', async () => {
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        openTab('Backtest');
        expect(await screen.findByText('walk-forward:12')).toBeInTheDocument();
        expect(runWalkForwardBacktest).toHaveBeenCalledTimes(1);
        expect(await screen.findByText('vista-track-record')).toBeInTheDocument();
        expect(await screen.findByText('panel-dca')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Ejecutar backtest' })).toBeEnabled();
        // Cambiar de pestaña y volver no relanza la corrida.
        openTab('Joyas');
        openTab('Backtest');
        await screen.findByText('walk-forward:12');
        expect(runWalkForwardBacktest).toHaveBeenCalledTimes(1);
    });

    it('mientras calcula deshabilita el botón y avisa; «Ejecutar backtest» repite la corrida', async () => {
        let resolve!: (v: unknown) => void;
        runWalkForwardBacktest.mockReturnValueOnce(new Promise((r) => (resolve = r)));
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        openTab('Backtest');
        const busy = await screen.findByRole('button', { name: 'Calculando...' });
        expect(busy).toBeDisabled();
        expect(screen.getByText(/Calculando backtest walk-forward/)).toBeInTheDocument();
        await act(async () => resolve({ months: 6 }));
        expect(await screen.findByText('walk-forward:6')).toBeInTheDocument();
        runWalkForwardBacktest.mockResolvedValueOnce({ months: 24 });
        fireEvent.click(screen.getByRole('button', { name: 'Ejecutar backtest' }));
        expect(await screen.findByText('walk-forward:24')).toBeInTheDocument();
        expect(runWalkForwardBacktest).toHaveBeenCalledTimes(2);
    });

    it('si el servidor devuelve un valor inesperado (null) se muestra el error en vez de romper', async () => {
        runWalkForwardBacktest.mockResolvedValue(null as never);
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        openTab('Backtest');
        expect(await screen.findByText(/No se pudo calcular el backtest/)).toBeInTheDocument();
    });

    it('un error devuelto por el servidor se muestra y Reintentar vuelve a llamar', async () => {
        runWalkForwardBacktest.mockResolvedValueOnce({ error: 'Sin datos de precios' });
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        openTab('Backtest');
        expect(await screen.findByText('Sin datos de precios')).toBeInTheDocument();
        expect(screen.getByText(/No se pudo calcular el backtest/)).toBeInTheDocument();
        expect(screen.queryByText(/walk-forward:/)).not.toBeInTheDocument();
        runWalkForwardBacktest.mockResolvedValueOnce({ months: 9 });
        fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
        expect(await screen.findByText('walk-forward:9')).toBeInTheDocument();
        expect(screen.queryByText('Sin datos de precios')).not.toBeInTheDocument();
    });

    it('una excepción (Error o valor suelto) también se muestra como error', async () => {
        runWalkForwardBacktest.mockRejectedValueOnce(new Error('Red caída'));
        const { unmount } = render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        openTab('Backtest');
        expect(await screen.findByText('Red caída')).toBeInTheDocument();
        unmount();
        runWalkForwardBacktest.mockRejectedValueOnce('texto suelto');
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        openTab('Backtest');
        expect(await screen.findByText('texto suelto')).toBeInTheDocument();
    });

    it('Estrategia: carga los picks de la estrategia activa (no los iniciales) y los pasa al rebalanceo', async () => {
        let resolve!: (v: ProPick[]) => void;
        generateProPicksForStrategy.mockReturnValueOnce(new Promise((r) => (resolve = r)));
        render(<ProPicksTabs strategies={strategies} initialPicks={[pick('INICIAL')]} generatedAt="2026-10-27" />);
        openTab('Estrategia y rebalanceo');
        expect(await screen.findByText('selector:adaptive')).toBeInTheDocument();
        expect(await screen.findByText('ficha:adaptive:Adaptativa:disponible')).toBeInTheDocument();
        expect(await screen.findByText(/^rebalanceo:adaptive:Adaptativa:loading::/)).toBeInTheDocument();
        expect(generateProPicksForStrategy).toHaveBeenCalledWith('adaptive');
        await act(async () => resolve([pick('AAPL'), pick('MSFT')]));
        expect(await screen.findByText(/rebalanceo:adaptive:Adaptativa:ready:AAPL,MSFT:/)).toBeInTheDocument();
        expect(screen.queryByText(/INICIAL/)).not.toBeInTheDocument();
    });

    it('cambiar de estrategia carga la nueva; volver a una ya cargada no pide de nuevo', async () => {
        generateProPicksForStrategy.mockImplementation(async (id: string) => [pick(id === 'value' ? 'VAL' : 'ADA')]);
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} generatedAt="2026-10-27" />);
        openTab('Estrategia y rebalanceo');
        await screen.findByText(/ready:ADA/);
        fireEvent.click(await screen.findByText('elegir-value'));
        await screen.findByText(/rebalanceo:value:Value:ready:VAL/);
        expect(generateProPicksForStrategy).toHaveBeenLastCalledWith('value');
        const calls = generateProPicksForStrategy.mock.calls.length;
        fireEvent.click(screen.getByText('elegir-momentum'));
        // Momentum no la provee el servidor: ficha «sin datos» con el nombre del catálogo.
        expect(await screen.findByText(/ficha:momentum:Momentum:sin-datos/)).toBeInTheDocument();
        await waitFor(() => expect(generateProPicksForStrategy.mock.calls.length).toBe(calls + 1));
        expect(generateProPicksForStrategy).toHaveBeenLastCalledWith('momentum');
    });

    it('si la carga de picks falla muestra el error y cambiar de estrategia lo limpia', async () => {
        generateProPicksForStrategy.mockRejectedValueOnce(new Error('boom'));
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} />);
        openTab('Estrategia y rebalanceo');
        expect(
            await screen.findByText(/rebalanceo:adaptive:Adaptativa:error::?.*No se pudieron cargar los picks de esta estrategia\./),
        ).toBeInTheDocument();
        generateProPicksForStrategy.mockResolvedValueOnce([pick('VAL')]);
        fireEvent.click(await screen.findByText('elegir-value'));
        expect(await screen.findByText(/rebalanceo:value:Value:ready:VAL:$/)).toBeInTheDocument();
    });

    it('un run nuevo desde Selección IA invalida los picks cacheados y se recargan al volver a Estrategia', async () => {
        generateProPicksForStrategy.mockResolvedValueOnce([pick('VIEJO', '2026-10-27')]);
        render(<ProPicksTabs strategies={strategies} initialPicks={[]} generatedAt="2026-10-27" />);
        openTab('Estrategia y rebalanceo');
        await screen.findByText(/ready:VIEJO/);
        openTab('Selección IA');
        fireEvent.click(screen.getByText('nuevo-run'));
        generateProPicksForStrategy.mockResolvedValueOnce([pick('NUEVO', '2026-11-01')]);
        openTab('Estrategia y rebalanceo');
        expect(await screen.findByText(/ready:NUEVO/)).toBeInTheDocument();
        expect(screen.queryByText(/VIEJO/)).not.toBeInTheDocument();
        expect(generateProPicksForStrategy).toHaveBeenCalledTimes(2);
    });

    it('sin estrategias del servidor la ficha de la estrategia inicial queda sin datos', async () => {
        render(<ProPicksTabs strategies={[]} initialPicks={[]} />);
        openTab('Estrategia y rebalanceo');
        expect(await screen.findByText(/ficha:adaptive:.*:sin-datos/)).toBeInTheDocument();
    });
});


it('el enlace desde la cuenta demo abre directamente los resultados de IA', async () => {
    render(<ProPicksTabs strategies={strategies} initialPicks={[]} initialTab="paper" />);
    expect(screen.getByRole('tab', { name: 'Resultados simulados de la IA' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('vista-paper')).toBeInTheDocument();
});
