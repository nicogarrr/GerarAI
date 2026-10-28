import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/watchlist.actions', () => ({
    getExtendedQuote: vi.fn(),
}));

import { getExtendedQuote } from '@/lib/actions/watchlist.actions';
import { requestCache } from '@/lib/cache/requestCache';
import ExtendedHoursLine from '@/components/common/ExtendedHoursLine';

const mocked = vi.mocked(getExtendedQuote);

const POST_QUOTE = {
    symbol: 'ASTS', price: 101.5, currency: 'USD', change_percent: 0.4,
    price_session: 'post', session: 'post', source: 'yahoo', status: 'ok',
    timestamp: 1_790_000_000, regular_close_timestamp: 1_789_990_000,
} as const;

beforeEach(() => {
    requestCache.clear();
});

describe('ExtendedHoursLine: deduplicación de lecturas por símbolo', () => {
    it('dos instancias montadas a la vez (tarjetas + tabla) hacen UNA sola lectura', async () => {
        mocked.mockResolvedValue(POST_QUOTE as never);
        render(
            <>
                <ExtendedHoursLine symbol="ASTS" currency="USD" />
                <ExtendedHoursLine symbol="ASTS" currency="USD" />
            </>,
        );
        await waitFor(() => expect(screen.getAllByText(/Post-cierre/).length).toBe(2));
        expect(mocked).toHaveBeenCalledTimes(1);
    });

    it('símbolos distintos sí leen por separado', async () => {
        mocked.mockResolvedValue(null as never);
        render(
            <>
                <ExtendedHoursLine symbol="ASTS" currency="USD" />
                <ExtendedHoursLine symbol="AAPL" currency="USD" />
            </>,
        );
        await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
    });

    it('un remontaje dentro del TTL no repite la lectura', async () => {
        mocked.mockResolvedValue(POST_QUOTE as never);
        const first = render(<ExtendedHoursLine symbol="ASTS" currency="USD" />);
        await waitFor(() => expect(screen.getByText(/Post-cierre/)).toBeInTheDocument());
        first.unmount();
        render(<ExtendedHoursLine symbol="ASTS" currency="USD" />);
        await waitFor(() => expect(screen.getByText(/Post-cierre/)).toBeInTheDocument());
        expect(mocked).toHaveBeenCalledTimes(1);
    });

    it('una lectura fallida no queda fijada: el siguiente montaje reintenta', async () => {
        mocked.mockRejectedValueOnce(new Error('red'));
        const first = render(<ExtendedHoursLine symbol="ASTS" currency="USD" />);
        await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
        first.unmount();
        mocked.mockResolvedValue(POST_QUOTE as never);
        render(<ExtendedHoursLine symbol="ASTS" currency="USD" />);
        await waitFor(() => expect(screen.getByText(/Post-cierre/)).toBeInTheDocument());
        expect(mocked).toHaveBeenCalledTimes(2);
    });
});
