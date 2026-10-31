import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/analyst-targets.actions', () => ({
    getListingAnalystTargetsBatch: vi.fn(),
}));

import { getListingAnalystTargetsBatch } from '@/lib/actions/analyst-targets.actions';
import { requestCache } from '@/lib/cache/requestCache';
import AnalystTargetLine from '@/components/common/AnalystTargetLine';

const mocked = vi.mocked(getListingAnalystTargetsBatch);

const TARGETS = {
    status: 'available', mean: 120, currency: 'USD', count: 12, high: 150, low: 90,
    source: 'yahoo', asOf: '2026-10-28T00:00:00Z',
} as never;

beforeEach(() => {
    requestCache.clear();
});

describe('AnalystTargetLine: deduplicación de lecturas por símbolo', () => {
    it('dos instancias montadas a la vez (tarjetas + tabla) hacen UNA sola lectura', async () => {
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, TARGETS])));
        render(
            <>
                <AnalystTargetLine symbol="ASTS" quoteSymbol="ASTS" currency="USD" referencePrice={100} />
                <AnalystTargetLine symbol="ASTS" quoteSymbol="ASTS" currency="USD" referencePrice={100} />
            </>,
        );
        await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    });

    it('un remontaje dentro del TTL no repite la lectura', async () => {
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, TARGETS])));
        const first = render(<AnalystTargetLine symbol="ASTS" quoteSymbol="ASTS" currency="USD" referencePrice={100} />);
        await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
        first.unmount();
        render(<AnalystTargetLine symbol="ASTS" quoteSymbol="ASTS" currency="USD" referencePrice={100} />);
        await waitFor(() => expect(screen.getAllByText(/120/).length).toBeGreaterThan(0));
        expect(mocked).toHaveBeenCalledTimes(1);
    });

    it('una lectura fallida no queda fijada: el siguiente montaje reintenta', async () => {
        mocked.mockRejectedValueOnce(new Error('red'));
        const first = render(<AnalystTargetLine symbol="ASTS" quoteSymbol="ASTS" currency="USD" referencePrice={100} />);
        await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
        first.unmount();
        mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, TARGETS])));
        render(<AnalystTargetLine symbol="ASTS" quoteSymbol="ASTS" currency="USD" referencePrice={100} />);
        await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
    });
});
