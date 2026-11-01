import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));

import { generateMetadata } from '@/app/(root)/temas/page';
import es from '@/lib/i18n/messages/es/themes.json';
import en from '@/lib/i18n/messages/en/themes.json';

const flat = (obj: object, prefix = ''): string[] =>
    Object.entries(obj).flatMap(([k, v]) => (typeof v === 'object' && v ? flat(v, `${prefix}${k}.`) : [`${prefix}${k}`]));

describe('Temas en inglés', () => {
    it('título de la pestaña según idioma', async () => {
        mocks.locale = 'en';
        expect((await generateMetadata()).title).toBe('Themes');
        mocks.locale = 'es';
        expect((await generateMetadata()).title).toBe('Temas');
    });

    it('mismas claves y mismos marcadores en los dos idiomas', () => {
        expect(flat(en.page).sort()).toEqual(flat(es.page).sort());
        expect(en.page.brainQuestion).toContain('{name}');
        expect(en.page.coverage).toBe('{n}/{total} with data');
    });
});
