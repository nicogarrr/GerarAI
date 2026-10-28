import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProPick } from '@/lib/actions/proPicks.actions';

const { generateEnhancedProPicksWithRun, generateFunnelRunNow, addToWatchlist, toastSuccess, toastError } = vi.hoisted(() => ({
    generateEnhancedProPicksWithRun: vi.fn(),
    generateFunnelRunNow: vi.fn(),
    addToWatchlist: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
}));
vi.mock('@/lib/actions/proPicks.actions', () => ({ generateEnhancedProPicksWithRun }));
vi.mock('@/lib/actions/propicks-funnel.actions', () => ({ generateFunnelRunNow }));
vi.mock('@/lib/actions/watchlist.actions', () => ({ addToWatchlist }));
vi.mock('sonner', () => ({ toast: { success: toastSuccess, error: toastError } }));

import EnhancedProPicksContent from '@/components/proPicks/EnhancedProPicksContent';

const pick = (over: Record<string, unknown> = {}): ProPick =>
    ({
        symbol: 'AAPL',
        company: 'Apple Inc',
        score: 82.5,
        grade: 'A-',
        categoryScores: { value: 75, growth: 70, profitability: 60, cashFlow: 65, momentum: 55, debtLiquidity: 50 },
        reasons: [],
        confidenceReasons: [{ text: 'Sube un 12% en 12 meses', metric: 'return12M', value: 12 }],
        confidence: 78,
        confidenceLevel: 'Media',
        asOf: '2026-10-27',
        facts: {},
        currentPrice: 150,
        priceAsOf: '2026-10-27',
        priceCurrency: 'USD',
        sector: 'Technology',
        ...over,
    }) as unknown as ProPick;

const result = (picks: ProPick[], extra: Record<string, unknown> = {}) => ({
    picks,
    runAsOf: '2026-10-28',
    passedCount: picks.length,
    ...extra,
});

beforeEach(() => {
    vi.clearAllMocks();
});

describe('EnhancedProPicksContent: lista', () => {
    it('muestra cada pick con posición, símbolo, enlace a la ficha, nota, confianza y motivos verificables', () => {
        render(
            <EnhancedProPicksContent
                initialPicks={[pick(), pick({ symbol: 'MSFT', company: 'Microsoft', score: 72, grade: 'B', sector: 'Technology' })]}
                generatedAt="2026-10-27T10:00:00Z"
                initialPassedCount={2}
            />,
        );
        expect(screen.getByText('Top 2')).toBeInTheDocument();
        const links = screen.getAllByRole('link');
        expect(links.map((l) => l.getAttribute('href'))).toEqual(['/research/AAPL', '/research/MSFT']);
        const first = within(links[0]);
        expect(first.getByText('#1')).toBeInTheDocument();
        expect(first.getByText('AAPL')).toBeInTheDocument();
        expect(first.getByText('A-')).toBeInTheDocument();
        expect(first.getByText(/82[,.]5/)).toBeInTheDocument();
        expect(first.getByText(/Media \(78\/100\)/)).toBeInTheDocument();
        expect(first.getByText('Sube un 12% en 12 meses').parentElement).toHaveAttribute(
            'title',
            'Dato verificado: return12M = 12',
        );
        expect(first.getByText(/Precio registrado/)).toBeInTheDocument();
        expect(screen.getByText(/Datos: /)).toBeInTheDocument();
        expect(screen.getByText(/puntuación mínima de 70 ordenadas por puntuación general/)).toBeInTheDocument();
    });

    it('un pick con potencial >0 enseña el porcentaje con signo; sin precio registrado no inventa precio', () => {
        render(
            <EnhancedProPicksContent
                initialPicks={[pick({ upsidePotential: 20.4, priceAsOf: undefined })]}
                generatedAt="2026-10-27"
            />,
        );
        expect(screen.getByText(/\+20[,.]4/)).toBeInTheDocument();
        expect(screen.getByText('Potencial (12m)')).toBeInTheDocument();
        expect(screen.queryByText(/Precio registrado/)).not.toBeInTheDocument();
    });

    it('una JOYA sustituye a la nota y las categorías sin datos salen n/d, nunca un 50', () => {
        render(
            <EnhancedProPicksContent
                initialPicks={[
                    pick({
                        isStrongBuy: true,
                        categoryScores: { value: 50, growth: 50, profitability: 50, cashFlow: 50, momentum: 50, debtLiquidity: 50 },
                        facts: { valoracion_neutral_sin_datos: 'si' },
                    }),
                ]}
                generatedAt="2026-10-27"
            />,
        );
        expect(screen.getByText(/JOYA/)).toBeInTheDocument();
        expect(screen.queryByText('A-')).not.toBeInTheDocument();
        expect(screen.getByText('n/d*')).toBeInTheDocument();
        expect(screen.getByText(/Sin datos para puntuarla/)).toBeInTheDocument();
    });

    it('sin categorías neutrales no hay nota de «sin datos»', () => {
        render(<EnhancedProPicksContent initialPicks={[pick()]} generatedAt="2026-10-27" />);
        expect(screen.queryByText('n/d*')).not.toBeInTheDocument();
        expect(screen.queryByText(/Sin datos para puntuarla/)).not.toBeInTheDocument();
    });
});

describe('EnhancedProPicksContent: estados vacíos', () => {
    it('sin run publicado ofrece generar la selección y la genera y consulta después', async () => {
        generateFunnelRunNow.mockResolvedValue({ passed_count: 3, universe_size: 500 });
        generateEnhancedProPicksWithRun.mockResolvedValue(result([pick()], { passedCount: 3 }));
        const onRunUpdated = vi.fn();
        render(<EnhancedProPicksContent initialPicks={[]} onRunUpdated={onRunUpdated} />);
        expect(screen.getByText('Sin selección')).toBeInTheDocument();
        expect(screen.getByText('Sin selección publicada')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Generar selección ahora' }));
        expect(await screen.findByText('#1')).toBeInTheDocument();
        expect(generateFunnelRunNow).toHaveBeenCalledTimes(1);
        expect(generateEnhancedProPicksWithRun).toHaveBeenCalledTimes(1);
        expect(onRunUpdated).toHaveBeenCalledWith('2026-10-28');
        expect(screen.getByRole('status')).toHaveTextContent('Selección consultada: 1 empresa.');
    });

    it('si generar el run devuelve error lo dice y no consulta picks', async () => {
        generateFunnelRunNow.mockResolvedValue({ error: 'backend caído' });
        render(<EnhancedProPicksContent initialPicks={[]} />);
        fireEvent.click(screen.getByRole('button', { name: 'Generar selección ahora' }));
        expect(await screen.findByText('No se pudo generar la selección. Inténtalo de nuevo.')).toBeInTheDocument();
        expect(generateEnhancedProPicksWithRun).not.toHaveBeenCalled();
        expect(screen.getByText('Reintenta para consultar el último run disponible.')).toBeInTheDocument();
    });

    it('si generar el run lanza una excepción muestra el mismo error y se puede reintentar', async () => {
        generateFunnelRunNow.mockRejectedValueOnce(new Error('x'));
        render(<EnhancedProPicksContent initialPicks={[]} />);
        fireEvent.click(screen.getByRole('button', { name: 'Generar selección ahora' }));
        await screen.findByText('No se pudo generar la selección. Inténtalo de nuevo.');
        generateFunnelRunNow.mockResolvedValue({ passed_count: 0, universe_size: 400 });
        generateEnhancedProPicksWithRun.mockResolvedValue(result([], { passedCount: 0 }));
        fireEvent.click(screen.getAllByRole('button', { name: 'Reintentar' })[0]);
        expect(await screen.findByText(/0 empresas\. El último embudo no seleccionó ninguna/)).toBeInTheDocument();
    });

    it('run generado sin empresas aptas lo explica con las cifras del universo', async () => {
        generateFunnelRunNow.mockResolvedValue({ passed_count: 0, universe_size: 400 });
        let resolve!: (v: unknown) => void;
        generateEnhancedProPicksWithRun.mockReturnValue(new Promise((r) => (resolve = r)));
        render(<EnhancedProPicksContent initialPicks={[]} />);
        fireEvent.click(screen.getByRole('button', { name: 'Generar selección ahora' }));
        expect(await screen.findByText('Procesando...')).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent('Consultando selección...');
        await act(async () => resolve(result([], { passedCount: 0 })));
        expect(await screen.findByText('Sin candidatos aptos')).toBeInTheDocument();
        expect(screen.getByText(/La selección del .* no contiene candidatos/)).toBeInTheDocument();
    });

    it('con run que seleccionó empresas pero filtros que excluyen todo, lo distingue de un embudo vacío', async () => {
        generateEnhancedProPicksWithRun.mockResolvedValue(result([], { passedCount: 12 }));
        render(<EnhancedProPicksContent initialPicks={[]} generatedAt="2026-10-27" initialPassedCount={12} />);
        expect(screen.getByText(/Ninguna acción de la selección del .* cumple los filtros actuales/)).toBeInTheDocument();
        fireEvent.click(screen.getAllByRole('button', { name: 'Actualizar selección' })[1]);
        expect(await screen.findByText(/Consulta completada: 0 empresas con estos filtros\. El último embudo sí seleccionó 12/)).toBeInTheDocument();
        expect(generateFunnelRunNow).not.toHaveBeenCalled();
    });
});

describe('EnhancedProPicksContent: actualizar y filtros', () => {
    it('Actualizar consulta con los filtros por defecto y no avisa si el run no cambia', async () => {
        generateEnhancedProPicksWithRun.mockResolvedValue(result([pick(), pick({ symbol: 'MSFT' })], { runAsOf: '2026-10-27' }));
        const onRunUpdated = vi.fn();
        render(<EnhancedProPicksContent initialPicks={[pick()]} generatedAt="2026-10-27" onRunUpdated={onRunUpdated} />);
        fireEvent.click(screen.getByRole('button', { name: 'Actualizar selección' }));
        expect(await screen.findByText('Top 2')).toBeInTheDocument();
        expect(generateEnhancedProPicksWithRun).toHaveBeenCalledWith({
            timePeriod: 'month',
            limit: 20,
            minScore: 70,
            sector: 'all',
            sortBy: 'score',
        });
        expect(onRunUpdated).not.toHaveBeenCalled();
    });

    it('un segundo clic mientras hay una consulta en curso no lanza otra', async () => {
        let resolve!: (v: unknown) => void;
        generateEnhancedProPicksWithRun.mockReturnValue(new Promise((r) => (resolve = r)));
        render(<EnhancedProPicksContent initialPicks={[pick()]} generatedAt="2026-10-27" />);
        const button = screen.getByRole('button', { name: 'Actualizar selección' });
        fireEvent.click(button);
        fireEvent.click(button);
        expect(generateEnhancedProPicksWithRun).toHaveBeenCalledTimes(1);
        expect(screen.getByRole('button', { name: 'Actualizando selección...' })).toBeDisabled();
        await act(async () => resolve(result([pick()])));
        expect(screen.getByRole('button', { name: 'Actualizar selección' })).toBeEnabled();
    });

    it('si la consulta falla conserva los resultados anteriores y permite reintentar', async () => {
        generateEnhancedProPicksWithRun.mockRejectedValueOnce(new Error('timeout'));
        render(<EnhancedProPicksContent initialPicks={[pick()]} generatedAt="2026-10-27" />);
        fireEvent.click(screen.getByRole('button', { name: 'Actualizar selección' }));
        expect(await screen.findByText('No se pudo actualizar la selección. Los resultados anteriores se conservan.')).toBeInTheDocument();
        expect(screen.getByText('AAPL')).toBeInTheDocument();
        generateEnhancedProPicksWithRun.mockResolvedValueOnce(result([pick(), pick({ symbol: 'KO' })]));
        fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
        expect(await screen.findByText('Top 2')).toBeInTheDocument();
        expect(screen.queryByText(/No se pudo actualizar la selección/)).not.toBeInTheDocument();
    });

    it('Aplicar filtros consulta y el texto de cabecera refleja los filtros aplicados, no el borrador', async () => {
        generateEnhancedProPicksWithRun.mockResolvedValue(result([pick()]));
        render(<EnhancedProPicksContent initialPicks={[pick()]} generatedAt="2026-10-27" />);
        fireEvent.click(screen.getByRole('button', { name: /Aplicar Filtros/ }));
        expect(await screen.findByText(/Selección consultada: 1 empresa/)).toBeInTheDocument();
        expect(screen.getByText(/puntuación mínima de 70/)).toBeInTheDocument();
    });
});

describe('EnhancedProPicksContent: seguir en watchlist', () => {
    it('añade a la watchlist sin navegar, avisa y deja el botón desactivado', async () => {
        addToWatchlist.mockResolvedValue({ success: true });
        render(<EnhancedProPicksContent initialPicks={[pick()]} generatedAt="2026-10-27" />);
        const button = screen.getAllByRole('button').find((b) => b.closest('a')) as HTMLElement;
        const notPrevented = fireEvent.click(button);
        expect(notPrevented).toBe(false); // preventDefault: no sigue el enlace de la tarjeta
        await vi.waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('AAPL añadido a la watchlist'));
        expect(addToWatchlist).toHaveBeenCalledWith('AAPL', 'Apple Inc');
        expect(button).toBeDisabled();
        fireEvent.click(button);
        expect(addToWatchlist).toHaveBeenCalledTimes(1);
    });

    it('si el servidor dice que no, o lanza, avisa del error y se puede volver a intentar', async () => {
        addToWatchlist.mockResolvedValueOnce({ success: false });
        render(<EnhancedProPicksContent initialPicks={[pick()]} generatedAt="2026-10-27" />);
        const button = screen.getAllByRole('button').find((b) => b.closest('a')) as HTMLElement;
        fireEvent.click(button);
        await vi.waitFor(() => expect(toastError).toHaveBeenCalledWith('No se pudo añadir a la watchlist'));
        expect(button).toBeEnabled();
        addToWatchlist.mockRejectedValueOnce(new Error('x'));
        fireEvent.click(button);
        await vi.waitFor(() => expect(toastError).toHaveBeenCalledTimes(2));
        expect(toastSuccess).not.toHaveBeenCalled();
    });
});
