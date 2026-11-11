import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const m = vi.hoisted(() => ({ targets: vi.fn(), history: vi.fn() }));
vi.mock('@/lib/actions/analyst-panels.actions', () => ({ readAnalystTargets: m.targets, readAnalystHistory: m.history }));
vi.mock('@/lib/i18n/client', () => ({ useT: () => (key: string) => key }));
vi.mock('@/components/research/AnalystTargetsView', () => ({ AnalystTargetsView: ({ data, currency }: any) => <p>{data?.symbol ?? 'targets unavailable'} {currency}</p> }));
vi.mock('@/components/research/AnalystHistoryView', () => ({ AnalystHistoryView: ({ data }: any) => <p>{data?.symbol ?? 'history unavailable'}</p>, AnalystHistorySkeleton: () => <p>history loading</p> }));
import { DeferredAnalystTargets, DeferredAnalystHistory } from '@/components/research/DeferredAnalystPanels';
import MobileCollapse from '@/components/ui/mobile-collapse';
let desktop = false;
let changed: () => void;
beforeEach(() => {
    vi.clearAllMocks(); desktop = false;
    m.targets.mockResolvedValue({ symbol: 'AAPL targets' }); m.history.mockResolvedValue({ symbol: 'AAPL history' });
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: desktop, addEventListener: (_: string, cb: () => void) => { changed = cb; }, removeEventListener: vi.fn() })));
});
it('mobile hidden panel does no read; open loads once and close/reopen retains it', async () => {
    render(<MobileCollapse deferMount title="Analistas"><DeferredAnalystTargets symbol="AAPL" currency="USD" /></MobileCollapse>);
    expect(m.targets).not.toHaveBeenCalled();
    const button = screen.getByRole('button', { name: 'Analistas' }); fireEvent.click(button);
    await screen.findByText('AAPL targets USD'); expect(m.targets).toHaveBeenCalledTimes(1);
    fireEvent.click(button); fireEvent.click(button); expect(m.targets).toHaveBeenCalledTimes(1);
});
it('desktop loads immediately and viewport transition activates hidden mobile content', async () => {
    desktop = true;
    const view = render(<MobileCollapse deferMount title="History"><DeferredAnalystHistory symbol="AAPL" /></MobileCollapse>);
    await screen.findByText('AAPL history'); expect(m.history).toHaveBeenCalledTimes(1); view.unmount();
    desktop = false;
    render(<MobileCollapse deferMount title="History"><DeferredAnalystHistory symbol="MSFT" /></MobileCollapse>);
    expect(m.history).toHaveBeenCalledTimes(1);
    await act(async () => { desktop = true; changed(); });
    await waitFor(() => expect(m.history).toHaveBeenCalledWith('MSFT'));
});
it('reuses initial targets promise instead of a duplicate action; failed reads show unavailable', async () => {
    const view = render(<DeferredAnalystTargets symbol="AAPL" initial={Promise.resolve({ symbol: 'shared' } as any)} />);
    await screen.findByText('shared'); expect(m.targets).not.toHaveBeenCalled(); view.unmount();
    m.history.mockRejectedValue(new Error('offline'));
    render(<DeferredAnalystHistory symbol="AAPL" />); await screen.findByText('history unavailable');
});
it('symbol change/unmount ignores old result, retaining no stale company data', async () => {
    let resolve!: (value: any) => void;
    m.targets.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const view = render(<DeferredAnalystTargets symbol="AAPL" />);
    expect(screen.getByRole('status')).toBeInTheDocument();
    view.rerender(<DeferredAnalystTargets symbol="MSFT" />);
    await screen.findByText('AAPL targets');
    await act(async () => resolve({ symbol: 'obsolete AAPL' }));
    expect(screen.queryByText('obsolete AAPL')).not.toBeInTheDocument();
    view.unmount();
});
