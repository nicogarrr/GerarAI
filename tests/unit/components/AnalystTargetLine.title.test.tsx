import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/analyst-targets.actions', () => ({
    getListingAnalystTargets: vi.fn(),
}));

import { getListingAnalystTargets } from '@/lib/actions/analyst-targets.actions';
import { requestCache } from '@/lib/cache/requestCache';
import AnalystTargetLine from '@/components/common/AnalystTargetLine';

const mocked = vi.mocked(getListingAnalystTargets);

const TARGETS = {
    status: 'available', mean: 1000, currency: 'USD', firms: 20, fetchedAt: null, source: 'Yahoo Finance', note: null,
} as never;

beforeEach(() => {
    requestCache.clear();
    mocked.mockReset();
});

describe('AnalystTargetLine: el title no pinta el proveedor', () => {
    it('declara el caracter no oficial y el detalle por firma, nunca data.source', async () => {
        mocked.mockResolvedValue(TARGETS);
        const { container } = render(<AnalystTargetLine symbol="ASTS" quoteSymbol="ASTS" currency="USD" referencePrice={800} />);
        await waitFor(() => {
            const span = container.querySelector('span[title]');
            expect(span).not.toBeNull();
        });
        const title = container.querySelector('span[title]')!.getAttribute('title')!;
        expect(title).not.toContain('Yahoo');
        expect(title).toContain('Fuente no oficial');
        expect(title).toContain('20 firmas');
    });
});
