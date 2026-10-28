/**
 * Guard de consultas redundantes: /watchlist y /portfolio montan las tarjetas
 * móviles Y la tabla de escritorio a la vez (solo cambia el CSS), así que cada
 * ExtendedHoursLine y cada AnalystTargetLine se montaban DOS veces por fila:
 * 2 lecturas idénticas por símbolo tras el primer pintado (4 por fila entre
 * ambas líneas). Las dos líneas deben pasar por requestCache (deduplica las
 * concurrentes y guarda el dato un TTL corto) en vez de llamar a la acción a
 * pelo.
 *
 * Ejecución: node --experimental-strip-types --test scripts/watchlist-line-dedupe-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const extended = readFileSync('components/common/ExtendedHoursLine.tsx', 'utf8');
const targets = readFileSync('components/common/AnalystTargetLine.tsx', 'utf8');

test('ExtendedHoursLine deduplica por símbolo vía requestCache con TTL', () => {
    assert.match(extended, /import \{ requestCache \} from '@\/lib\/cache\/requestCache'/);
    assert.match(extended, /requestCache\.get\(`extended-quote:\$\{symbol\.toUpperCase\(\)\}`/);
    assert.match(extended, /EXTENDED_QUOTE_TTL_S = 60/);
});

test('AnalystTargetLine deduplica por símbolo y listado vía requestCache con TTL', () => {
    assert.match(targets, /import \{ requestCache \} from '@\/lib\/cache\/requestCache'/);
    assert.match(targets, /requestCache\.get\(/);
    assert.match(targets, /`analyst-targets:\$\{symbol\.toUpperCase\(\)\}:/);
    assert.match(targets, /ANALYST_TARGETS_TTL_S = 300/);
});
