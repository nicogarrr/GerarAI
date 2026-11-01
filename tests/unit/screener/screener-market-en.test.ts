import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('@/lib/actions/market.actions', () => ({}));
vi.mock('@/lib/actions/ticker-context.actions', () => ({}));
vi.mock('@/lib/actions/screener.actions', () => ({}));
vi.mock('@/lib/actions/watchlist.actions', () => ({}));

import { generateMetadata } from '@/app/(root)/screener/page';
import { quoteObserved } from '@/lib/market/quote-observed';
import es from '@/lib/i18n/messages/es/screener.json';
import en from '@/lib/i18n/messages/en/screener.json';

describe('Mercado (/screener) en inglés', () => {
    it('título y descripción siguen el idioma', async () => {
        mocks.locale = 'en';
        expect(await generateMetadata()).toEqual({ title: 'Explore stocks', description: en.metaDescription });
        mocks.locale = 'es';
        expect((await generateMetadata()).title).toBe('Explorar acciones');
    });

    it('los textos de la página no nombran proveedor en ningún idioma', () => {
        for (const dict of [es, en]) {
            expect(`${dict.metaDescription} ${dict.engineDownText}`).not.toMatch(/Finnhub/);
        }
        expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
    });

    it('la hora de la cotización en inglés', () => {
        expect(quoteObserved(1792180800, 'daily_candle_open', 'en')).toMatch(/^Last daily candle \(open time\) .*2026.*UTC$/);
        expect(quoteObserved(1792180800, 'quote', 'en')).toMatch(/^Quote /);
        expect(quoteObserved(null, undefined, 'en')).toBe('Date N/A: provider has no date');
        expect(quoteObserved(null)).toBe('Fecha N/D: proveedor sin fecha');
    });
});
