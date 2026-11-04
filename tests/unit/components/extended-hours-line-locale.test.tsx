import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/watchlist.actions', () => ({
    getExtendedQuotes: vi.fn(),
}));

import { getExtendedQuotes } from '@/lib/actions/watchlist.actions';
import { requestCache } from '@/lib/cache/requestCache';
import { LocaleProvider } from '@/lib/i18n/client';
import ExtendedHoursLine from '@/components/common/ExtendedHoursLine';

const mocked = vi.mocked(getExtendedQuotes);

// Post-cierre ya pasado (sesión distinta): «Último post-cierre · <fecha hora>».
const QUOTE = {
    symbol: 'MSFT', price: 1543.78, currency: 'USD', change_percent: 1.25,
    price_session: 'post', session: 'closed', source: 'yahoo', status: 'ok',
    timestamp: 1_790_000_000, regular_close_timestamp: 1_789_990_000,
} as const;

beforeEach(() => {
    requestCache.clear();
    mocked.mockImplementation(async (keys: string[]) => Object.fromEntries(keys.map((k) => [k, QUOTE])) as never);
});

// E2E local (4-nov-2026, /watchlist y /portfolio en inglés): la línea salía
// «Último post-cierre · 4 nov, 01:59 CET: 1.543,78 US$» con el idioma en inglés.
describe('ExtendedHoursLine: idioma activo', () => {
    it('en inglés: etiqueta, precio y % en inglés', async () => {
        const { container } = render(
            <LocaleProvider locale="en"><ExtendedHoursLine symbol="MSFT" currency="USD" /></LocaleProvider>,
        );
        await waitFor(() => expect(screen.getByText(/Last after-hours/)).toBeVisible());
        const text = container.textContent ?? '';
        expect(text).toContain('$1,543.78');
        expect(text).toContain('+1.25%');
        expect(text).not.toMatch(/Último|US\$|1\.543,78|1,25/);
    });

    it('en castellano no cambia: «Último post-cierre», «1543,78 US$», «+1,25 %»', async () => {
        const { container } = render(
            <LocaleProvider locale="es"><ExtendedHoursLine symbol="MSFT" currency="USD" /></LocaleProvider>,
        );
        await waitFor(() => expect(screen.getByText(/Último post-cierre/)).toBeVisible());
        const text = container.textContent ?? '';
        expect(text).toMatch(/1\.?543,78\s?US\$/);
        expect(text).toMatch(/\+1,25\s?%/);
    });
});
