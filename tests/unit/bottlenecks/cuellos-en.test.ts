import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));

import { generateMetadata } from '@/app/(root)/cuellos/page';
import es from '@/lib/i18n/messages/es/bottlenecks.json';
import en from '@/lib/i18n/messages/en/bottlenecks.json';

describe('Cuellos de botella en inglés', () => {
    it('título de la pestaña según idioma', async () => {
        mocks.locale = 'en';
        expect((await generateMetadata()).title).toBe('Bottlenecks');
        mocks.locale = 'es';
        expect((await generateMetadata()).title).toBe('Cuellos de botella');
    });

    it('mismas claves en los dos idiomas', () => {
        expect(Object.keys(en.page).sort()).toEqual(Object.keys(es.page).sort());
        expect(en.page.sourcesShort).toBe('{n} of {min} independent sources · not enough evidence');
    });
});
