import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { LiveMarketsPanel } from '@/components/markets/LiveMarketsPanel';
import { LIVE_QUOTE_GROUPS, type LiveMarketsResult, type LiveQuote } from '@/lib/market/live-quotes';

const { read } = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('@/lib/actions/live-quotes.actions', () => ({ getLiveMarkets: read }));

const T0 = Date.UTC(2026, 10, 13, 15, 0, 0);
const first = LIVE_QUOTE_GROUPS[0].specs[0];
// Cotización descargada en T0 con 40 s de antigüedad en ese momento.
const quote: LiveQuote = {
    ...first, price: 16000, change: 10, changePercent: 0.17,
    timestamp: T0 / 1000 - 40, currency: 'USD', session: 'regular',
    exchangeName: 'TEST', instrumentType: 'INDEX',
};
const snapshot: LiveMarketsResult = {
    fetchedAt: T0,
    groups: LIVE_QUOTE_GROUPS.map((group, index) => ({
        key: group.key, quotes: group.specs.map((_, item) => index === 0 && item === 0 ? quote : null),
    })),
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: false });
    vi.setSystemTime(T0);
});
afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

describe('LiveMarketsPanel antigüedad honesta', () => {
    it('el rótulo de antigüedad sigue creciendo con el reloj aunque fallen los refrescos', async () => {
        // Refrescos caídos: se conserva el último dato bueno.
        read.mockRejectedValue(new Error('live_quotes_unavailable'));
        render(<LiveMarketsPanel initial={snapshot} />);
        // Al montar, el reloj arranca: misma edad que en la descarga.
        expect(screen.getByText('hace 40 s')).toBeInTheDocument();

        // Pasan 6 minutos sin refresco bueno: el rótulo envejece, no se congela.
        act(() => {
            vi.setSystemTime(T0 + 6 * 60_000);
            vi.advanceTimersByTime(31_000);
        });
        expect(screen.getByText('hace ~7 min')).toBeInTheDocument();
        expect(screen.queryByText('hace 40 s')).not.toBeInTheDocument();
    });
});
