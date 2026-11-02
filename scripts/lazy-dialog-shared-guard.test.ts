/**
 * Guarda del estado compartido de los gatillos de diálogo diferido:
 * AddTransactionButton, WatchlistAddButton y WorkProductButton usan el MISMO
 * hook (useLazyDialog) para open/openedOnce/onOpenChange en vez de tres
 * copias; la regla «la primera apertura deja el diálogo montado» vive una
 * sola vez.
 *
 * Ejecución: node --experimental-strip-types --test scripts/lazy-dialog-shared-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const hook = readFileSync('hooks/useLazyDialog.ts', 'utf8');
const buttons = [
    ['AddTransactionButton', readFileSync('components/portfolio/AddTransactionButton.tsx', 'utf8')],
    ['WatchlistAddButton', readFileSync('components/watchlist/WatchlistAddButton.tsx', 'utf8')],
    ['WorkProductButton', readFileSync('components/work-products/WorkProductButton.tsx', 'utf8')],
] as const;

describe('gatillos de diálogo diferido: estado compartido', () => {
    it('los tres botones usan useLazyDialog', () => {
        for (const [name, source] of buttons) {
            assert.match(source, /useLazyDialog/, `${name} usa el hook compartido`);
            assert.match(source, /openedOnce/, `${name} sigue montando el diálogo tras la primera apertura`);
            assert.match(source, /onPointerDown/, `${name} conserva la precarga en pointerdown`);
            assert.match(source, /onFocus/, `${name} conserva la precarga en focus`);
        }
    });

    it('la regla «abrir marca la primera apertura» vive una sola vez', () => {
        assert.match(hook, /if \(next\) setOpenedOnce\(true\)/);
        for (const [name, source] of buttons) {
            assert.doesNotMatch(source, /setOpenedOnce/, `${name} no reimplementa la regla`);
        }
    });
});
