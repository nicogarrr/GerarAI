import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import DcaEvaluateButton from '@/components/watchlist/DcaEvaluateButton';
import DcaWatchCardToggle from '@/components/watchlist/DcaWatchCardToggle';
import DcaHitRatesPopover from '@/components/watchlist/DcaHitRatesPopover';
import fixture from '../watchlist-dca-card.fixture.json';
const m = vi.hoisted(() => ({ start: vi.fn(), poll: vi.fn(), card: vi.fn(), history: vi.fn(), refresh: vi.fn(), success: vi.fn(), warning: vi.fn(), error: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: m.refresh }) }));
vi.mock('sonner', () => ({ toast: { success: m.success, warning: m.warning } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: m.error }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ startDcaManualJob: m.start, getDcaManualJob: m.poll, getDcaHitRates: m.history }));
vi.mock('@/lib/actions/dca-watch-card.actions', () => ({ getDcaWatchCard: m.card }));
const mount = (node: React.ReactNode) => render(<LocaleProvider locale="en">{node}</LocaleProvider>);
const click = async (name: RegExp | string) => { await act(async () => { fireEvent.click(screen.getByRole('button', { name })); }); };
const advance = async (ms = 5000) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
beforeEach(() => { Object.values(m).forEach(f => f.mockReset()); });
afterEach(() => { vi.useRealTimers(); });

describe('manual evaluation', () => {
    beforeEach(() => { vi.useFakeTimers(); m.start.mockResolvedValue({ success: true, runId: 7 }); });
    it('starts only on demand and does not poll before5s, then reports a complete batch and unlocks', async () => {
        m.poll.mockResolvedValue({ success: true, status: 'ok', summary: { evaluated: 3, alerted: [{ symbol: 'MSFT' }], skipped: [{ symbol: 'X' }], errors: [], pending_remaining: 2 } });
        mount(<DcaEvaluateButton />); expect(m.start).not.toHaveBeenCalled(); await click('Run pending now');
        expect(screen.getByRole('button', { name: 'Evaluating…' })).toBeDisabled(); expect(screen.getByRole('status')).toHaveTextContent('Batch accepted');
        await advance(4999); expect(m.poll).not.toHaveBeenCalled(); await advance(1);
        expect(m.poll).toHaveBeenCalledWith(7); expect(m.success).toHaveBeenCalledWith(expect.stringMatching(/3 evaluated.*1 new alert.*1 without enough data.*2 left/));
        expect(m.warning).not.toHaveBeenCalled(); expect(m.refresh).toHaveBeenCalledOnce(); expect(screen.queryByRole('status')).not.toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Run pending now' })).toBeEnabled();
    });
    it('reports partial results as warning and never as a successful complete run', async () => {
        m.poll.mockResolvedValue({ success: true, status: 'ok', summary: { evaluated: 1, alerted: [], skipped: [], errors: [{ symbol: 'X' }] } });
        mount(<DcaEvaluateButton />); await click('Run pending now'); await advance();
        expect(m.warning).toHaveBeenCalledWith(expect.stringMatching(/Partial.*1 company with errors/)); expect(m.success).not.toHaveBeenCalled();
    });
    it.each([{ success: false, message: 'quota reached' }, { success: true }])('rejects unaccepted or missing-ID receipts without polling', async receipt => {
        m.start.mockResolvedValue(receipt); mount(<DcaEvaluateButton />); await click('Run pending now'); await advance(300_000);
        expect(m.error).toHaveBeenCalledOnce(); expect(m.poll).not.toHaveBeenCalled(); expect(m.refresh).not.toHaveBeenCalled();
    });
    it.each(['interrupted', 'background'] as const)('shows %s as status, not a success or error', async state => {
        m.poll.mockResolvedValue({ success: true, status: state === 'background' ? 'running' : 'interrupted' });
        mount(<DcaEvaluateButton />); await click('Run pending now'); await advance(state === 'background' ? 300_000 : 5000);
        expect(m.poll).toHaveBeenCalledTimes(state === 'background' ? 60 : 1); expect(screen.getByRole('status')).toHaveTextContent(state === 'background' ? /Still running/ : /Run interrupted/);
        expect(m.success).not.toHaveBeenCalled(); expect(m.error).not.toHaveBeenCalled(); expect(m.refresh).toHaveBeenCalledOnce();
    });
    it.each(['poll', 'start', 'throw'] as const)('surfaces %s failure and releases busy state', async mode => {
        if (mode === 'start') m.start.mockRejectedValue(new Error('offline'));
        if (mode === 'poll') m.poll.mockResolvedValue({ success: false, message: 'poll failed' });
        if (mode === 'throw') m.poll.mockRejectedValue(new Error('poll network'));
        mount(<DcaEvaluateButton />); await click('Run pending now'); await advance(); expect(m.error).toHaveBeenCalledOnce(); expect(screen.getByRole('button', { name: 'Run pending now' })).toBeEnabled();
    });
    it('does not poll or refresh after unmount during the waiting interval', async () => {
        const view = mount(<DcaEvaluateButton />); await click('Run pending now'); view.unmount(); await advance(300_000); expect(m.poll).not.toHaveBeenCalled(); expect(m.refresh).not.toHaveBeenCalled(); expect(m.error).not.toHaveBeenCalled();
    });
});

describe('on-demand DCA card', () => {
    it('fetches on first open, shows loading, and caches a good response across close/reopen', async () => {
        let resolve!: (value: unknown) => void; m.card.mockImplementation(() => new Promise(r => { resolve = r; })); mount(<DcaWatchCardToggle symbol="INTC" />);
        expect(m.card).not.toHaveBeenCalled(); await click('DCA card'); expect(screen.getByRole('status')).not.toBeEmptyDOMElement(); expect(screen.getByRole('button', { name: 'DCA card' })).toHaveAttribute('aria-expanded', 'true');
        await act(async () => { resolve(fixture); }); expect(screen.getByTestId('dca-card-current')).not.toBeEmptyDOMElement();
        await click('DCA card'); expect(screen.queryByTestId('dca-card-current')).not.toBeInTheDocument(); await click('DCA card'); expect(m.card).toHaveBeenCalledTimes(1); expect(m.card).toHaveBeenCalledWith('INTC');
    });
    it.each(['null', 'throw'])('retries %s on reopen instead of permanently caching failure', async mode => {
        if (mode === 'null') m.card.mockResolvedValueOnce(null); else m.card.mockRejectedValueOnce(new Error('offline'));
        m.card.mockResolvedValue(fixture); mount(<DcaWatchCardToggle symbol="INTC" />); await click('DCA card');
        expect(screen.queryByTestId('dca-card-current')).not.toBeInTheDocument(); await click('DCA card'); await click('DCA card');
        expect(m.card).toHaveBeenCalledTimes(2); expect(screen.getByTestId('dca-card-current')).not.toBeEmptyDOMElement();
    });
    it('does not duplicate an in-flight read when toggled while loading', async () => {
        let resolve!: (value: unknown) => void; m.card.mockImplementation(() => new Promise(r => { resolve = r; })); mount(<DcaWatchCardToggle symbol="INTC" />);
        await click('DCA card'); await click('DCA card'); await click('DCA card'); expect(m.card).toHaveBeenCalledOnce(); await act(async () => { resolve(fixture); });
    });
});

describe('on-demand history popover', () => {
    it('does not fetch until opened and retries a failed/null response, then caches data', async () => {
        m.history.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(null).mockResolvedValue({ symbol: 'INTC', available: false, reason: 'No fixture history' });
        mount(<DcaHitRatesPopover symbol="INTC" />); const name = 'DCA signal history for INTC'; expect(m.history).not.toHaveBeenCalled();
        for (let i = 0; i < 3; i++) { await click(name); expect(m.history).toHaveBeenCalledTimes(i + 1); await click(name); }
        await click(name); expect(m.history).toHaveBeenCalledTimes(3); expect(screen.getByText('No fixture history')).toBeInTheDocument();
    });
});
