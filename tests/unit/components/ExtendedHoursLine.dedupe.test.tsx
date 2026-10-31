import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/watchlist.actions', () => ({
    getExtendedQuotes: vi.fn(),
}));

import { getExtendedQuotes } from '@/lib/actions/watchlist.actions';
import { requestCache } from '@/lib/cache/requestCache';
import ExtendedHoursLine from '@/components/common/ExtendedHoursLine';

const mocked = vi.mocked(getExtendedQuotes);

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
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, POST_QUOTE])) as never);
        render(
            <>
                <ExtendedHoursLine symbol="ASTS" currency="USD" />
                <ExtendedHoursLine symbol="ASTS" currency="USD" />
            </>,
        );
        await waitFor(() => expect(screen.getAllByText(/Post-cierre/).length).toBe(2));
        expect(mocked).toHaveBeenCalledTimes(1);
    });

    it('símbolos distintos viajan en la MISMA llamada batch como claves separadas', async () => {
        // 31-oct-2026: antes cada símbolo era una invocación serverless (12
        // filas = 12 POSTs medidos en prod). Ahora una ventana = UNA llamada
        // con todas las claves; la protección es que cada fila pide su clave.
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, null])) as never);
        render(
            <>
                <ExtendedHoursLine symbol="ASTS" currency="USD" />
                <ExtendedHoursLine symbol="AAPL" currency="USD" />
            </>,
        );
        await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
        expect(mocked).toHaveBeenCalledWith(['ASTS', 'AAPL']);
    });

    it('un remontaje dentro del TTL no repite la lectura', async () => {
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, POST_QUOTE])) as never);
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
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, POST_QUOTE])) as never);
        render(<ExtendedHoursLine symbol="ASTS" currency="USD" />);
        await waitFor(() => expect(screen.getByText(/Post-cierre/)).toBeInTheDocument());
        expect(mocked).toHaveBeenCalledTimes(2);
    });
});
