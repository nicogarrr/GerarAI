/**
 * F386: un backend caído no debe pintarse como "Tu watchlist está vacía".
 * Ejecución: node --experimental-strip-types --test scripts/watchlist-unavailable-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = (p: string): string => readFileSync(join(root, p), 'utf8');

describe('watchlist: fallo del backend vs lista vacía', () => {
    it('la acción expone el estado unavailable', () => {
        const actions = source('lib/actions/watchlist.actions.ts');
        assert.match(actions, /export async function getWatchlistState/);
        assert.match(actions, /unavailable: true/);
    });
    it('la página muestra un estado no disponible antes del vacío', () => {
        const page = source('app/(root)/watchlist/page.tsx');
        assert.match(page, /getWatchlistState\(\)/);
        assert.ok(page.indexOf('watchlist-unavailable') < page.indexOf('Tu watchlist está vacía'));
        assert.match(page, /No se pudo cargar tu watchlist/);
    });
});
