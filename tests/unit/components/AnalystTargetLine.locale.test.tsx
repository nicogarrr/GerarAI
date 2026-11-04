import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/analyst-targets.actions', () => ({
    getListingAnalystTargetsBatch: vi.fn(),
}));

import { getListingAnalystTargetsBatch } from '@/lib/actions/analyst-targets.actions';
import { requestCache } from '@/lib/cache/requestCache';
import { LocaleProvider } from '@/lib/i18n/client';
import AnalystTargetLine from '@/components/common/AnalystTargetLine';

const mocked = vi.mocked(getListingAnalystTargetsBatch);
const target = (over: Record<string, unknown> = {}) => ({
    status: 'available', mean: 633.13, currency: 'USD', firms: 20, fetchedAt: null, source: 'Yahoo Finance', note: null, ...over,
}) as never;

beforeEach(() => {
    requestCache.clear();
});

const serve = (value: unknown) => mocked.mockImplementation(async (items: { symbol: string; quoteSymbol?: string | null }[]) =>
    Object.fromEntries(items.map((it) => [`${it.symbol.toUpperCase()}:${(it.quoteSymbol ?? '').toUpperCase()}`, value])) as never);

// E2E local (4-nov-2026, /watchlist y /portfolio en inglés): la columna de
// objetivo salía «633,13 US$ +26,6 %» y «N/D» con el idioma en inglés.
describe('AnalystTargetLine: cifras con el idioma activo', () => {
    it('en inglés: objetivo y recorrido con formato inglés', async () => {
        serve(target());
        const { container } = render(
            <LocaleProvider locale="en"><AnalystTargetLine symbol="MSFT" currency="USD" referencePrice={500} /></LocaleProvider>,
        );
        expect(await screen.findByText('$633.13')).toBeInTheDocument();
        expect(screen.getByText('+26.6%')).toBeInTheDocument();
        expect(container.textContent).not.toMatch(/US\$|633,13|26,6/);
    });

    it('en inglés sin consenso: «N/A», no «N/D»', async () => {
        serve(target({ status: 'unavailable', mean: null }));
        render(
            <LocaleProvider locale="en"><AnalystTargetLine symbol="MSFT" currency="USD" referencePrice={500} /></LocaleProvider>,
        );
        expect(await screen.findByText('N/A')).toBeInTheDocument();
        expect(screen.queryByText('N/D')).toBeNull();
    });

    it('en castellano sigue igual', async () => {
        serve(target());
        render(
            <LocaleProvider locale="es"><AnalystTargetLine symbol="MSFT" currency="USD" referencePrice={500} /></LocaleProvider>,
        );
        expect(await screen.findByText(/633,13\s?US\$/)).toBeInTheDocument();
        expect(screen.getByText(/\+26,6\s?%/)).toBeInTheDocument();
    });
});
