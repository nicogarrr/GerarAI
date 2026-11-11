import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { LiveMarketsPanel } from '@/components/markets/LiveMarketsPanel';
import { LIVE_QUOTE_GROUPS, type LiveMarketsResult, type LiveQuote } from '@/lib/market/live-quotes';

const { read } = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('@/lib/actions/live-quotes.actions', () => ({ getLiveMarkets: read }));

const first = LIVE_QUOTE_GROUPS[0].specs[0];
const quote: LiveQuote = {
    ...first, price: 16000, change: 10, changePercent: 0.17,
    timestamp: 1_800_000_000, currency: 'USD', session: 'regular',
    exchangeName: 'TEST', instrumentType: 'INDEX',
};
const makeSnapshot = (fetchedAt: number, valid: boolean): LiveMarketsResult => ({
    fetchedAt,
    groups: LIVE_QUOTE_GROUPS.map((group, index) => ({
        key: group.key, quotes: group.specs.map((_, item) => valid && index === 0 && item === 0 ? quote : null),
    })),
});
const old = makeSnapshot(Date.UTC(2026, 10, 11, 9), true);
const outage = makeSnapshot(Date.UTC(2026, 10, 11, 10), false);
const recovered = makeSnapshot(Date.UTC(2026, 10, 11, 11), true);
const clickRefresh = () => fireEvent.click(screen.getByRole('button', { name: 'Actualizar ahora' }));

beforeEach(() => vi.clearAllMocks());
afterEach(() => cleanup());

describe('LiveMarketsPanel total outage', () => {
    it('keeps the last good snapshot and OLD update time when every refreshed quote is null', async () => {
        read.mockResolvedValue(outage);
        render(<LiveMarketsPanel initial={old} />);
        expect(screen.getByText(/Actualizado a las 10:00:00/)).toBeInTheDocument();
        clickRefresh();
        await screen.findByText(/la última actualización falló/);
        expect(screen.getByText(/Actualizado a las 10:00:00/)).toBeInTheDocument();
        expect(screen.queryByText(/Actualizado a las 11:00:00/)).not.toBeInTheDocument();
        expect(screen.getByText(first.name)).toBeInTheDocument();
        expect(screen.getByText('16.000,00')).toBeInTheDocument();
    });

    it.each([null, outage])('initial total failure is provider unavailable, not a fresh update or normal empty group (%s)', (initial) => {
        render(<LiveMarketsPanel initial={initial} />);
        expect(screen.getAllByText(/Proveedor de cotizaciones no disponible/).length).toBeGreaterThan(0);
        expect(screen.queryByText(/Actualizado a las/)).not.toBeInTheDocument();
        expect(screen.queryByText('No hay datos disponibles ahora. Se reintenta cada minuto.')).not.toBeInTheDocument();
    });

    it('accepts partial success with N/D rows and clears the warning on recovery', async () => {
        read.mockResolvedValueOnce(outage).mockResolvedValueOnce(recovered);
        render(<LiveMarketsPanel initial={old} />);
        clickRefresh();
        await screen.findByText(/la última actualización falló/);
        clickRefresh();
        await screen.findByText(/Actualizado a las 12:00:00/);
        expect(screen.queryByText(/la última actualización falló/)).not.toBeInTheDocument();
        expect(screen.getByText('16.000,00')).toBeInTheDocument();
        expect(screen.getAllByText('N/D').length).toBeGreaterThan(0);
    });

    it('recovers from an unavailable first load and preserves data on a rejected refresh', async () => {
        read.mockResolvedValueOnce(recovered).mockRejectedValueOnce(new Error('fixture outage'));
        render(<LiveMarketsPanel initial={null} />);
        clickRefresh();
        await screen.findByText(/Actualizado a las 12:00:00/);
        expect(screen.queryByText(/Proveedor de cotizaciones no disponible/)).not.toBeInTheDocument();
        clickRefresh();
        await screen.findByText(/la última actualización falló/);
        expect(screen.getByText(/Actualizado a las 12:00:00/)).toBeInTheDocument();
        await waitFor(() => expect(screen.getByRole('button', { name: 'Actualizar ahora' })).not.toBeDisabled());
    });
});
