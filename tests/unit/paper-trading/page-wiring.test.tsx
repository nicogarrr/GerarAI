import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PaperTradingPage, { generateMetadata } from '@/app/(root)/paper-trading/page';

const mocks = vi.hoisted(() => ({
    account: vi.fn(), history: vi.fn(), valuation: vi.fn(),
    place: vi.fn(), convert: vi.fn(), chain: vi.fn(),
    panel: vi.fn(), revalidate: vi.fn(),
}));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidate }));
vi.mock('@/lib/actions/manual-demo.actions', () => ({
    getManualDemoAccount: mocks.account, getManualDemoValuation: mocks.valuation,
    getManualDemoHistory: mocks.history, placeManualOrder: mocks.place,
    convertManualDemoCurrency: mocks.convert,
}));
vi.mock('@/lib/actions/demo-option-chain.actions', () => ({ getDemoOptionChain: mocks.chain }));
vi.mock('@/components/paper-trading/ManualDemoPanel', () => ({ ManualDemoPanel: (p: unknown) => { mocks.panel(p); return null; } }));
vi.mock('@/components/ui/page-header', () => ({ PageHeader: () => null }));

const STATE = { cashEUR: 100, cashUSD: 50, realizedEUR: 0, realizedUSD: 0, positions: [], violations: [], notices: [] };
const ORDER = { clientOrderId: 'x', kind: 'accion', symbol: 'MSFT', name: 'Microsoft', side: 'buy', openClose: 'open', quantity: 1, status: 'filled', fillPrice: 10, currency: 'USD', fee: 0, executedAt: 1, rejectReason: null, createdAt: 1, simulated: true };
const INPUT = { kind: 'accion', symbol: 'MSFT' } as never;

beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('MONGODB_URI', 'mongodb://test.invalid/local');
    mocks.account.mockResolvedValue({ ok: true, state: STATE });
    mocks.history.mockResolvedValue({ ok: true, orders: [ORDER], hasMore: true, nextBefore: 'cursor-1' });
    mocks.valuation.mockResolvedValue({ ok: true, valuation: { total: 1 }, asOf: 123 });
});
afterEach(() => vi.unstubAllEnvs());

async function renderPage() {
    render(await PaperTradingPage());
    return mocks.panel.mock.calls[0][0] as Record<string, any>;
}

describe('paper-trading page wiring (server actions + data path)', () => {
    it('passes fetched account, history cursor, valuation and the real chain action to the panel', async () => {
        const props = await renderPage();
        expect(props.account).toBe(STATE);
        expect(props.ledger).toEqual([ORDER]);
        expect(props.historyHasMore).toBe(true);
        expect(props.historyNextBefore).toBe('cursor-1');
        expect(props.valuation).toEqual({ total: 1 });
        expect(props.valuationAsOf).toBe(123);
        expect(props.fetchOptionChain).toBe(mocks.chain);
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    it('degrades valuation and history failures honestly: empty ledger, visible loadError, null valuation', async () => {
        mocks.valuation.mockResolvedValue({ ok: false });
        mocks.history.mockResolvedValue({ ok: false, message: 'Sin historial' });
        const props = await renderPage();
        expect(props.ledger).toEqual([]);
        expect(props.historyHasMore).toBe(false);
        expect(props.historyNextBefore).toBeNull();
        expect(props.valuation).toBeNull();
        expect(props.valuationAsOf).toBeNull();
        expect(screen.getByRole('alert')).toHaveTextContent('Sin historial');
    });
    it('submitFill maps outcomes and revalidates the ledger only on a persisted rejection', async () => {
        const { submitFill } = await renderPage();
        mocks.place.mockResolvedValue({ ok: true, outcome: 'filled', reason: null, state: STATE });
        await expect(submitFill(INPUT)).resolves.toEqual({ ok: true, outcome: 'filled', reason: null, state: STATE });
        expect(mocks.revalidate).not.toHaveBeenCalled();
        mocks.place.mockResolvedValue({ ok: true, outcome: 'rejected', reason: 'Saldo insuficiente', state: STATE });
        await expect(submitFill(INPUT)).resolves.toEqual({ ok: true, outcome: 'rejected', reason: 'Saldo insuficiente', state: STATE });
        expect(mocks.revalidate).toHaveBeenCalledWith('/paper-trading');
        mocks.place.mockResolvedValue({ ok: false, message: 'Sin sesión' });
        await expect(submitFill(INPUT)).resolves.toEqual({ ok: false, error: 'Sin sesión' });
    });
    it('submitFx maps outcomes and revalidates only on a persisted rejection', async () => {
        const { submitFx } = await renderPage();
        mocks.convert.mockResolvedValue({ ok: true, outcome: 'filled', reason: null, state: STATE });
        await expect(submitFx(INPUT)).resolves.toEqual({ ok: true, outcome: 'filled', reason: null, state: STATE });
        expect(mocks.revalidate).not.toHaveBeenCalled();
        mocks.convert.mockResolvedValue({ ok: true, outcome: 'rejected', reason: 'Límite', state: STATE });
        await expect(submitFx(INPUT)).resolves.toEqual({ ok: true, outcome: 'rejected', reason: 'Límite', state: STATE });
        expect(mocks.revalidate).toHaveBeenCalledWith('/paper-trading');
        mocks.convert.mockResolvedValue({ ok: false, message: 'Sin sesión' });
        await expect(submitFx(INPUT)).resolves.toEqual({ ok: false, error: 'Sin sesión' });
    });
    it('refreshValuation passes through the honest flags on success and the message on failure', async () => {
        const { refreshValuation } = await renderPage();
        const payload = { ok: true, valuation: { total: 2 }, asOf: 456, listingUnavailable: ['X'], quoteFetchFailed: true, retryAfterSeconds: 30 };
        mocks.valuation.mockResolvedValue(payload);
        await expect(refreshValuation()).resolves.toEqual({
            ok: true, valuation: { total: 2 }, asOf: 456, listingUnavailable: ['X'], quoteFetchFailed: true, retryAfterSeconds: 30,
        });
        mocks.valuation.mockResolvedValue({ ok: false, message: 'Fuente saturada' });
        await expect(refreshValuation()).resolves.toEqual({ ok: false, error: 'Fuente saturada' });
    });
    it('loadMoreHistory pages with a stable cursor and surfaces action failures', async () => {
        const { loadMoreHistory } = await renderPage();
        mocks.history.mockResolvedValue({ ok: true, orders: [ORDER], hasMore: false, nextBefore: null });
        await expect(loadMoreHistory('cursor-1')).resolves.toEqual({ ok: true, orders: [ORDER], hasMore: false, nextBefore: null });
        expect(mocks.history).toHaveBeenCalledWith({ before: 'cursor-1' });
        mocks.history.mockResolvedValue({ ok: false, message: 'Cursor inválido' });
        await expect(loadMoreHistory('cursor-1')).resolves.toEqual({ ok: false, message: 'Cursor inválido' });
    });
    it('generateMetadata returns the localized title and description', async () => {
        const meta = await generateMetadata();
        expect(meta.title).toBeTruthy();
        expect(meta.description).toBeTruthy();
    });
});
