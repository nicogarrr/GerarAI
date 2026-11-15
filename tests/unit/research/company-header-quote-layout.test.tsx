import { Suspense } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import type { ExtendedQuote } from '@/lib/market/extended-quote';

vi.mock('@/lib/i18n/client', async () => {
    const { createFormatters } = await import('@/lib/format');
    const fmt = createFormatters('es');
    const t = (key: string) => key;
    return { useFormat: () => fmt, useLocale: () => 'es', useT: () => t };
});
vi.mock('@/components/research/CompanyTechnicalWorkspace', () => ({ CompanyTechnicalWorkspace: () => <div data-testid="chart" /> }));
import { CompanyHeaderQuote } from '@/components/research/CompanyHeaderQuote';

const snapshot = { ticker: 'MSFT', currency: 'USD', exchange: 'NASDAQ', history: [] } as unknown as CompanyMarketSnapshot;
const live = {
    ticker: 'MSFT', fetched_at: 1788966000, source: 'fixture', status: 'available', price: 336.56, currency: 'USD', timestamp: 1788966000,
    price_session: 'regular', session: 'regular', change: 2.34, change_percent: 0.7,
} as ExtendedQuote;
let resolve: (value: Response) => void;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
    fetchMock = vi.fn(() => new Promise<Response>(r => { resolve = r; }));
    vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
async function respond(value: unknown, status = 200) {
    await act(async () => { resolve(new Response(JSON.stringify(value), { status })); });
}

it('reserves price and variation rows while loading and when a quote arrives', async () => {
    render(<CompanyHeaderQuote snapshot={snapshot} compact />);
    const price = screen.getByTestId('company-header-price-block');
    expect(price.querySelector('[aria-busy="true"]')).toHaveClass('min-h-10', 'sm:min-h-12');
    expect(price.querySelector('[aria-hidden="true"]')).toHaveClass('block', 'h-10', 'sm:h-12');
    expect(screen.getByTestId('company-header-quote-status')).toHaveClass('flow-root', 'min-h-9');
    expect(screen.queryByText(/0,70/)).not.toBeInTheDocument();
    await respond(live);
    expect(price).toHaveTextContent('336,56');
    expect(price).toHaveTextContent('+0,70');
    expect(price.querySelector('[aria-busy]')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument();
});

it.each([
    ['negative', { change: -2.34, change_percent: -0.7 }, '-0,70'],
    ['flat', { change: 0, change_percent: 0 }, '336,56'],
    ['closed', { session: 'cerrado', close_change_percent: -0.7, close_change: -2.34, close_change_date: '2026-09-08', close_change_previous_date: '2026-09-07' }, '-0,70'],
])('keeps the same reserved status slot for %s quotes', async (_name, overrides, text) => {
    render(<CompanyHeaderQuote snapshot={snapshot} compact />);
    await respond({ ...live, ...overrides });
    expect(screen.getByTestId('company-header-quote-status')).toHaveClass('flow-root', 'min-h-9');
    expect(screen.getByTestId('company-header-price-block')).toHaveTextContent(text);
});

it('full view keeps real metrics and the chart outside the reserved price block', async () => {
    render(<CompanyHeaderQuote snapshot={snapshot} />);
    await respond({ ...live, metrics_timestamp: live.timestamp, metrics_session: 'regular', open: 330, high: 340, low: 329,
        previous_close: 334.22, previous_close_timestamp: live.timestamp });
    expect(screen.getByTestId('company-metric-strip')).toHaveTextContent('330');
    expect(screen.getByTestId('chart')).toBeInTheDocument();
    expect(screen.getByTestId('company-header-price-block').querySelector('[data-testid="chart"]')).toBeNull();
});

it.each([['unavailable', { status: 'unavailable' }, 200], ['http error', {}, 503]])('shows honest %s in the reserved row', async (_name, value, status) => {
    render(<CompanyHeaderQuote snapshot={snapshot} compact />);
    await respond(value, status);
    expect(screen.getByTestId('company-header-quote-status')).toHaveTextContent('research.headerQuote.liveUnavailable');
    expect(screen.getByTestId('company-header-price-block')).toHaveTextContent('N/D');
});

it('on a failed read uses a dated chart fallback without pretending it is live', async () => {
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    render(<CompanyHeaderQuote snapshot={{ ...snapshot, history: [
        { date: '2026-09-07', close: 330, volume: null }, { date: '2026-09-08', close: 335, volume: null },
    ] }} />);
    await waitFor(() => expect(screen.getByTestId('company-header-price-block')).toHaveTextContent('335'));
    expect(screen.getByTestId('company-header-quote-status')).toHaveTextContent('research.headerQuote.liveUnavailable');
    expect(screen.getByTestId('company-metric-strip')).toHaveTextContent('330');
});

it('an initial server quote uses the same slots and does not issue another initial fetch', async () => {
    const initialQuote = Promise.resolve(live);
    await act(async () => { render(<Suspense fallback="loading"><CompanyHeaderQuote snapshot={snapshot} initialQuote={initialQuote} compact /></Suspense>); });
    expect(screen.getByTestId('company-header-price-block')).toHaveTextContent('336,56');
    expect(fetchMock).not.toHaveBeenCalled();
});

it('unmount aborts a pending read and does not publish its late response', async () => {
    const view = render(<CompanyHeaderQuote snapshot={snapshot} compact />);
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await respond(live);
    expect(screen.queryByTestId('company-header-quote')).not.toBeInTheDocument();
});

it('polls after five minutes, not before, and stops on unmount', async () => {
    vi.useFakeTimers();
    const view = render(<CompanyHeaderQuote snapshot={snapshot} compact />);
    await respond(live);
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(300_000); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await respond(live);
    view.unmount();
    await act(async () => { vi.advanceTimersByTime(300_000); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
});
