/**
 * Barra inferior móvil: 5 destinos que existen en la app y montada en el layout.
 * Ejecución: node --experimental-strip-types --test scripts/bottom-nav-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const constants = readFileSync('lib/constants.ts', 'utf8');
const block = constants.slice(constants.indexOf('export const MOBILE_TAB_ITEMS'));
const tabBlock = block.slice(0, block.indexOf('];'));
const hrefs = [...tabBlock.matchAll(/href: '([^']+)'/g)].map((m) => m[1]);

describe('barra inferior móvil', () => {
    it('tiene entre 4 y 5 destinos sin repetir', () => {
        assert.ok(hrefs.length >= 4 && hrefs.length <= 5, String(hrefs.length));
        assert.equal(new Set(hrefs).size, hrefs.length);
    });
    it('cada destino es una página real', () => {
        for (const href of hrefs) {
            assert.ok(existsSync(`app/(root)${href}/page.tsx`), href);
        }
    });
    it('el layout autenticado la monta y deja hueco bajo el contenido', () => {
        const layout = readFileSync('app/(root)/layout.tsx', 'utf8');
        assert.match(layout, /<BottomNav \/>/);
        assert.ok(layout.includes("pb-[calc(7.5rem+env(safe-area-inset-bottom))]"));
    });
    it('solo se ve en móvil (md:hidden)', () => {
        assert.match(readFileSync('components/layout/BottomNav.tsx', 'utf8'), /md:hidden/);
    });
});
