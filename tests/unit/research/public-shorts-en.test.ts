import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import en from '@/lib/i18n/messages/en/research.json';
import es from '@/lib/i18n/messages/es/research.json';

describe('public shorts page in English', () => {
    it('every research.publicShorts key used by the page exists in both languages', () => {
        const page = readFileSync('app/(root)/research/[ticker]/shorts/page.tsx', 'utf8');
        const keys = [...page.matchAll(/research\.publicShorts\.(\w+)/g)].map((m) => m[1]);
        expect(keys.length).toBeGreaterThan(15);
        for (const key of keys) {
            expect(en.publicShorts[key as keyof typeof en.publicShorts]).toBeTruthy();
            expect(es.publicShorts[key as keyof typeof es.publicShorts]).toBeTruthy();
        }
        expect(en.publicShorts.title).toBe('Public short positions · {ticker}');
        expect(en.publicShorts.derived).toBe('DERIVED');
        expect(page).not.toMatch(/Cortos públicos|Suma pública|Volver a la empresa/);
    });
});
