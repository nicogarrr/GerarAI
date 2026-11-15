import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import { ManualDemoPanel, type ManualDemoPanelProps, type RefreshResult } from '@/components/paper-trading/ManualDemoPanel';
import type { DemoPositionView, DemoStateView, HistoryPageResult, HistoryRow } from '@/components/paper-trading/submit';
import type { DemoValuation } from '@/lib/market/demo-valuation';
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => <input aria-label="Search" /> }));
const position: DemoPositionView = { instrumentKey: 'A:MSFT', name: 'Microsoft', kind: 'accion', currency: 'USD', quantity: 2, avgCost: 100, realizedPnl: 0, optionExpiry: null, optionBadge: null };
const account: DemoStateView = { cashEUR: 1000, cashUSD: 500, realizedEUR: 0, realizedUSD: 0, positions: [position], violations: [], notices: [] };
const valuation: DemoValuation = { rows: [{ ...position, status: 'valorada', price: 120, marketValue: 240, unrealizedPnl: 40, unrealizedPct: 20, currencyBasis: 'finnhub-listado', quoteLabel: 'Fixture quote', note: null }], totals: [{ currency: 'USD', marketValue: 240, unrealizedPnl: 40, costBasis: 200, valuedPositions: 1 }], coverage: { valued: 1, total: 1 } };
const success = (extra: Partial<Extract<RefreshResult, { ok: true }>> = {}): RefreshResult => ({ ok: true, valuation, asOf: Date.UTC(2026, 0, 1), listingUnavailable: false, quoteFetchFailed: false, retryAfterSeconds: null, ...extra });
const row = (i: number): HistoryRow => ({ clientOrderId: `row-${i}`, kind: 'accion', symbol: `T${i}`, name: `Trade ${i}`, side: 'buy', openClose: 'open', quantity: 1, status: 'filled', fillPrice: i, currency: 'USD', fee: 0, executedAt: Date.UTC(2026, 0, 1), rejectReason: null, createdAt: i, simulated: true });
const initialRows = Array.from({ length: 10 }, (_, i) => row(i));
function setup(overrides: Partial<ManualDemoPanelProps> = {}) {
    const props: ManualDemoPanelProps = { account, ledger: [], submitFill: vi.fn(), submitFx: vi.fn(), ...overrides };
    const view = render(<LocaleProvider locale="en"><ManualDemoPanel {...props} /></LocaleProvider>);
    const tab = async (name: string) => { await act(async () => { fireEvent.mouseDown(screen.getByRole('tab', { name }), { button: 0, ctrlKey: false }); }); };
    const rerender = (next: Partial<ManualDemoPanelProps>) => { Object.assign(props, next); view.rerender(<LocaleProvider locale="en"><ManualDemoPanel {...props} /></LocaleProvider>); };
    return { ...view, tab, rerender };
}
beforeEach(() => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    vi.useFakeTimers(); vi.setSystemTime(new Date('2026-11-15T12:00:00Z'));
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
const tick = async (ms = 60_000) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
const visible = async (state: 'hidden' | 'visible') => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: state });
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
};

describe('valuation refresh gates', () => {
    it('waits one minute, pauses while hidden, resumes on visible and cleans up on unmount', async () => {
        const refresh = vi.fn().mockResolvedValue(success()); const ui = setup({ refreshValuation: refresh });
        await tick(59_999); expect(refresh).not.toHaveBeenCalled(); await tick(1); expect(refresh).toHaveBeenCalledOnce();
        await visible('hidden'); await tick(180_000); expect(refresh).toHaveBeenCalledOnce();
        await visible('visible'); expect(refresh).toHaveBeenCalledTimes(2);
        ui.unmount(); await tick(180_000); await visible('visible'); expect(refresh).toHaveBeenCalledTimes(2);
    });
    it('does not poll accounts with no positions', async () => {
        const refresh = vi.fn(); setup({ account: { ...account, positions: [] }, refreshValuation: refresh });
        await tick(600_000); await visible('visible'); expect(refresh).not.toHaveBeenCalled();
    });
    it('shares one in-flight lock between manual and automatic refresh', async () => {
        let resolve!: (value: RefreshResult) => void; const refresh = vi.fn(() => new Promise<RefreshResult>(r => { resolve = r; }));
        const ui = setup({ refreshValuation: refresh }); await ui.tab('Positions');
        const button = screen.getByRole('button', { name: /check quotes/i }); fireEvent.click(button);
        expect(button).toBeDisabled(); await tick(180_000); expect(refresh).toHaveBeenCalledOnce();
        await act(async () => { resolve(success()); });
        expect(screen.getByRole('button', { name: /update quotes/i })).toBeEnabled();
        expect(screen.getAllByText(/Fixture quote/).length).toBeGreaterThan(0);
    });
    it.each(['error', 'network', 'listing', 'quotes'] as const)('backs off on %s, then resets to60s on success', async mode => {
        const refresh = vi.fn();
        if (mode === 'network') refresh.mockRejectedValueOnce(new Error('offline'));
        else refresh.mockResolvedValueOnce(mode === 'error' ? { ok: false, error: 'offline' } : success({ listingUnavailable: mode === 'listing', quoteFetchFailed: mode === 'quotes' }));
        refresh.mockResolvedValue(success()); setup({ refreshValuation: refresh });
        await tick(); expect(refresh).toHaveBeenCalledOnce(); await tick(); expect(refresh).toHaveBeenCalledOnce();
        await tick(); expect(refresh).toHaveBeenCalledTimes(2); await tick(); expect(refresh).toHaveBeenCalledTimes(3);
    });
    it('honors Retry-After independently of success/backoff', async () => {
        const refresh = vi.fn().mockResolvedValueOnce(success({ retryAfterSeconds: 240 })).mockResolvedValue(success()); setup({ refreshValuation: refresh });
        await tick(); await tick(180_000); expect(refresh).toHaveBeenCalledOnce(); await tick(); expect(refresh).toHaveBeenCalledTimes(2);
    });
    it('caps exponential backoff at16min instead of abandoning refresh', async () => {
        const refresh = vi.fn().mockResolvedValue({ ok: false, error: 'offline' }); setup({ refreshValuation: refresh });
        await tick();
        for (const gap of [120_000, 240_000, 480_000, 960_000, 960_000]) {
            const count = refresh.mock.calls.length; await tick(gap - 60_000); expect(refresh).toHaveBeenCalledTimes(count); await tick(); expect(refresh).toHaveBeenCalledTimes(count + 1);
        }
    });
    it('hides stale totals after quantity changes and explains why a new valuation is needed', async () => {
        const ui = setup({ valuation, refreshValuation: vi.fn() }); await ui.tab('Positions');
        expect(screen.getByText(/1 of 1|1 position/)).toBeInTheDocument();
        ui.rerender({ account: { ...account, positions: [{ ...position, quantity: 3 }] } });
        expect(screen.queryByText(/1 of 1|1 position/)).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: /check quotes/i })).toBeEnabled();
        expect(screen.queryByText('Fixture quote')).not.toBeInTheDocument();
    });
});

describe('cursor history', () => {
    it('loads the next cursor, deduplicates rows, supports previous and resets extras when first page changes', async () => {
        const load = vi.fn().mockResolvedValue({ ok: true, orders: [row(9), row(10)], hasMore: false, nextBefore: null });
        const ui = setup({ ledger: initialRows, historyHasMore: true, historyNextBefore: 'cursor-A', loadMoreHistory: load }); await ui.tab('History');
        expect(screen.getByText('T0')).toBeInTheDocument();
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /next/i })); });
        expect(load).toHaveBeenCalledWith('cursor-A'); expect(screen.getByText('T10')).toBeInTheDocument(); expect(screen.queryByText('T9')).not.toBeInTheDocument();
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /previous/i })); });
        expect(screen.getByText('T9')).toBeInTheDocument(); expect(load).toHaveBeenCalledOnce();
        ui.rerender({ ledger: [row(100)], historyHasMore: false, historyNextBefore: null });
        expect(screen.getByText('T100')).toBeInTheDocument(); expect(screen.queryByText('T10')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /next/i })).not.toBeInTheDocument();
    });
    it('shows load errors without throwing away the first page and can retry the same cursor', async () => {
        const load = vi.fn().mockResolvedValueOnce({ ok: false, message: 'History offline' }).mockResolvedValue({ ok: true, orders: [row(10)], hasMore: false, nextBefore: null });
        const ui = setup({ ledger: initialRows, historyHasMore: true, historyNextBefore: 'cursor-A', loadMoreHistory: load }); await ui.tab('History');
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /next/i })); });
        expect(screen.getByRole('alert')).toHaveTextContent('History offline'); expect(screen.getByText('T0')).toBeInTheDocument();
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /next/i })); });
        expect(load.mock.calls).toEqual([['cursor-A'], ['cursor-A']]); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    it('keeps page1 when the server has no more entries and disables pagination while loading', async () => {
        let resolve!: (value: HistoryPageResult) => void; const load = vi.fn(() => new Promise<HistoryPageResult>(r => { resolve = r; }));
        const ui = setup({ ledger: initialRows, historyHasMore: true, historyNextBefore: 'cursor-A', loadMoreHistory: load }); await ui.tab('History');
        fireEvent.click(screen.getByRole('button', { name: /next/i })); expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
        await act(async () => { resolve({ ok: true, orders: [], hasMore: false, nextBefore: null }); });
        expect(screen.getByText('T0')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: /next/i })).not.toBeInTheDocument();
    });
});
