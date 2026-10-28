import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PaperState, PaperScore, PaperTradeView } from '@/lib/actions/paper-trading.actions';
const mocks = vi.hoisted(() => ({ load: vi.fn(), feed: vi.fn() }));
vi.mock('@/lib/actions/paper-trading.actions', () => ({ getPaperTrading: mocks.load, feedPaperProposalsNow: mocks.feed }));
import PaperTradingView, { PaperTradingContent } from '@/components/proPicks/PaperTradingView';
const empty = (): PaperState => ({ trades: [], score: { groups: [] } });
const group = (over: Partial<PaperScore['groups'][number]> = {}): PaperScore['groups'][number] => ({
    horizon: 'five_years', currency: 'EUR', proposals: 10, closed: 4, open: 6, wins: 3, losses: 1,
    flat: 0, hit_rate: 0.75, realized_pnl: '12.5', unrealized_pnl: null, missing_marks: 2, ...over,
});
beforeEach(() => vi.clearAllMocks());

describe('Paper trading read-only loading and local mocked feed', () => {
    it('loads once and separates simulated model results from the manual demo account', async () => {
        let finish!: (data: PaperState) => void;
        mocks.load.mockReturnValue(new Promise(resolve => { finish = resolve; }));
        render(<PaperTradingView />);
        expect(screen.getByRole('status')).toHaveTextContent('Cargando cartera simulada');
        await act(async () => finish(empty()));
        expect(screen.getByRole('heading', { name: 'Resultados simulados de la IA' })).toBeVisible();
        expect(screen.getByRole('link', { name: 'Ir a mi cuenta demo' })).toHaveAttribute('href', '/paper-trading');
        expect(screen.getByText(/no de tus operaciones manuales/)).toBeVisible();
        expect(mocks.load).toHaveBeenCalledOnce();
        expect(mocks.feed).not.toHaveBeenCalled();
    });
    it('reports rejected loading without showing empty data or allowing generation', async () => {
        mocks.load.mockRejectedValue(new Error('offline'));
        render(<PaperTradingView />);
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar la cartera simulada.');
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });
    it('respects an explicit action error and does not interpret it as an empty portfolio', async () => {
        mocks.load.mockResolvedValue({ ...empty(), error: 'Sin acceso' });
        render(<PaperTradingView />);
        expect(await screen.findByRole('alert')).toHaveTextContent('Sin acceso');
        expect(screen.queryByText(/Sin propuestas del modelo/)).not.toBeInTheDocument();
    });
    it.each([false, true])('ignores late response after unmount, rejected=%s', async rejected => {
        let finish!: (data: PaperState) => void;
        let fail!: (reason: Error) => void;
        mocks.load.mockReturnValue(new Promise((resolve, reject) => { finish = resolve; fail = reject; }));
        const view = render(<PaperTradingView />);
        view.unmount();
        await act(async () => { if (rejected) fail(new Error('late')); else finish(empty()); });
        expect(view.container).toBeEmptyDOMElement();
    });
    it('blocks duplicate generation while pending and after successful queueing', async () => {
        let finish!: (value: { success: true }) => void;
        mocks.feed.mockReturnValue(new Promise(resolve => { finish = resolve; }));
        render(<PaperTradingContent data={empty()} />);
        fireEvent.click(screen.getByRole('button', { name: 'Generar propuestas simuladas' }));
        const pending = screen.getByRole('button', { name: 'Encolando generación...' });
        expect(pending).toBeDisabled(); expect(pending).toHaveAttribute('aria-busy', 'true');
        fireEvent.click(pending); expect(mocks.feed).toHaveBeenCalledOnce();
        await act(async () => finish({ success: true }));
        expect(screen.getByText(/Generación en curso/)).toBeVisible();
        expect(screen.getByRole('button')).toBeDisabled();
        expect(screen.getByRole('button')).toHaveAttribute('aria-busy', 'false');
    });
    it.each(['rejected', 'unsuccessful'])('recovers from %s feed and permits a successful retry', async mode => {
        if (mode === 'rejected') mocks.feed.mockRejectedValueOnce(new Error('offline'));
        else mocks.feed.mockResolvedValueOnce({ success: false, message: 'quota' });
        mocks.feed.mockResolvedValueOnce({ success: true });
        render(<PaperTradingContent data={empty()} />);
        fireEvent.click(screen.getByRole('button'));
        expect(await screen.findByText(/No se pudo encolar/)).toBeVisible();
        expect(screen.getByRole('button')).toBeEnabled();
        fireEvent.click(screen.getByRole('button'));
        expect(await screen.findByText(/Generación en curso/)).toBeVisible();
        expect(screen.queryByText(/No se pudo encolar/)).not.toBeInTheDocument();
        expect(mocks.feed).toHaveBeenCalledTimes(2);
    });
    it('keeps currency groups separate, formats ratios and distinguishes missing net data from zero', () => {
        render(<PaperTradingContent data={{ trades: [], score: { groups: [
            group(), group({ horizon: 'short', currency: 'sin_datos', hit_rate: null, realized_pnl_net: null }),
            group({ currency: 'USD', realized_pnl_net: '0', closed_net: 2, closed_distorted: 1 }),
        ] } }} />);
        const eur = screen.getByRole('heading', { name: 'Tesis 5 años · EUR' }).closest('article')!;
        expect(eur).toHaveTextContent('75 %');
        expect(eur).toHaveTextContent('12,5');
        expect(eur).toHaveTextContent('0 de 4');
        expect(within(eur).getByText('Resultado neto cerrado').nextElementSibling).toHaveTextContent('Sin datos');
        const usd = screen.getByRole('heading', { name: 'Tesis 5 años · USD' }).closest('article')!;
        expect(within(usd).getByText('Resultado neto cerrado').nextElementSibling).toHaveTextContent('0');
        expect(usd).toHaveTextContent('2 de 4');
        expect(screen.getByRole('heading', { name: 'Operación a 30 días · Sin divisa' })).toBeVisible();
        expect(screen.getByText(/Divisas separadas/)).toHaveTextContent('otra divisa nunca convertida');
    });
    it('renders supplied proposal cards and hides the empty-feed control', () => {
        const trade: PaperTradeView = { id: 1, ticker: 'LOCAL', direction: 'long', horizon: 'short', thesis: 'fixture', conviction: '0.5',
            proposed_entry: '100', stop: '90', target: '120', inference_basis: 'local', status: 'pending', currency: 'EUR',
            created_at: '2026-01-01T00:00:00Z', entry_price: null, exit_price: null, mark_price: null, entry_at: null,
            exit_at: null, mark_at: null, realized_pnl: null, unrealized_pnl: null, close_reason: null };
        render(<PaperTradingContent data={{ ...empty(), trades: [trade] }} />);
        expect(screen.getByRole('article', { name: 'Propuesta simulada LOCAL' })).toBeVisible();
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
        expect(screen.queryByText(/Sin propuestas del modelo/)).not.toBeInTheDocument();
    });
});
