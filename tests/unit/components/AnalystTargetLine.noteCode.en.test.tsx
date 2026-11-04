import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/analyst-targets.actions', () => ({
    getListingAnalystTargetsBatch: vi.fn(),
}));

import { getListingAnalystTargetsBatch } from '@/lib/actions/analyst-targets.actions';
import { requestCache } from '@/lib/cache/requestCache';
import AnalystTargetLine from '@/components/common/AnalystTargetLine';
import { LocaleProvider } from '@/lib/i18n/client';

const mocked = vi.mocked(getListingAnalystTargetsBatch);

// Lo que llega del backend sin consenso: nota en castellano + código estable.
const EMPTY = {
    status: 'empty', mean: null, currency: null, firms: 0, fetchedAt: null, source: 'x',
    note: 'No hay precios objetivo por analista para este valor.', noteCode: 'no_targets', instrumentType: null,
} as never;

beforeEach(() => {
    requestCache.clear();
    mocked.mockReset();
    mocked.mockImplementation(async (items: { symbol: string; quoteSymbol?: string | null }[]) =>
        Object.fromEntries(items.map((it) => [`${it.symbol.toUpperCase()}:${(it.quoteSymbol ?? '').toUpperCase()}`, EMPTY])),
    );
});

async function titleFor(locale: 'es' | 'en'): Promise<string> {
    const { container } = render(
        <LocaleProvider locale={locale}><AnalystTargetLine symbol="ZZZ" quoteSymbol="ZZZ" currency="USD" referencePrice={10} /></LocaleProvider>,
    );
    await waitFor(() => expect(container.querySelector('span[title]')).not.toBeNull());
    return container.querySelector('span[title]')!.getAttribute('title')!;
}

describe('AnalystTargetLine: la nota del backend se traduce por código', () => {
    it('en inglés el tooltip va en inglés', async () => {
        expect(await titleFor('en')).toBe('No analyst price targets for this stock.');
    });
    it('en castellano, el mismo texto que mandaba el backend', async () => {
        expect(await titleFor('es')).toBe('No hay precios objetivo por analista para este valor.');
    });
});
