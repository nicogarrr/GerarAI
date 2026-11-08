import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ getLiveMarkets: vi.fn(async () => null) }));
vi.mock('@/lib/actions/live-quotes.actions', () => ({ getLiveMarkets: mocks.getLiveMarkets }));

import { LiveMarketsPanel } from '@/components/markets/LiveMarketsPanel';
import { LocaleProvider } from '@/lib/i18n/client';

function setVisibility(state: DocumentVisibilityState) {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
}

describe('sondeo de mercados en directo', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        setVisibility('visible');
        mocks.getLiveMarkets.mockClear();
    });

    afterEach(() => {
        vi.useRealTimers();
        setVisibility('visible');
    });

    it('sondea cada minuto con la pestaña visible', async () => {
        render(<LocaleProvider locale="es"><LiveMarketsPanel initial={null} /></LocaleProvider>);
        await act(async () => {
            vi.advanceTimersByTime(120_000);
        });
        expect(mocks.getLiveMarkets).toHaveBeenCalledTimes(2);
    });

    it('no sondea con la pestaña oculta y refresca al volver', async () => {
        render(<LocaleProvider locale="es"><LiveMarketsPanel initial={null} /></LocaleProvider>);
        setVisibility('hidden');
        await act(async () => {
            vi.advanceTimersByTime(300_000);
        });
        expect(mocks.getLiveMarkets).not.toHaveBeenCalled();

        setVisibility('visible');
        await act(async () => {
            document.dispatchEvent(new Event('visibilitychange'));
        });
        expect(mocks.getLiveMarkets).toHaveBeenCalledTimes(1);
    });
});
