/**
 * Margen de seguridad con escenario base no positivo: N/D, nunca un porcentaje
 * (p. ej. -249 % sobre una base de -84.70, ficha de ASTS).
 *
 * Ejecución: node --experimental-strip-types --test scripts/thesis-mos-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types en runtime
import { marginOfSafetyDisplay, NA } from '../lib/format.ts';

const here = dirname(fileURLToPath(import.meta.url));
const memo = readFileSync(join(here, '..', 'components', 'research', 'ThesisMemo.tsx'), 'utf8');

describe('marginOfSafetyDisplay', () => {
    it('base negativa o cero -> N/D aunque haya margen guardado', () => {
        assert.equal(marginOfSafetyDisplay(-2.49, -84.7), NA);
        assert.equal(marginOfSafetyDisplay(-1, 0), NA);
        assert.equal(marginOfSafetyDisplay('-2.49', '-84.7'), NA);
    });
    it('base positiva muestra el porcentaje', () => {
        assert.notEqual(marginOfSafetyDisplay(0.2, 100), NA);
        assert.match(marginOfSafetyDisplay(0.2, 100), /20/);
    });
    it('sin margen -> N/D', () => {
        assert.equal(marginOfSafetyDisplay(null, 100), NA);
    });
    it('la ficha usa el helper, no pct() directo sobre margin_of_safety', () => {
        assert.match(memo, /marginOfSafetyDisplay\(knownMargin \? thesis\.margin_of_safety : archivedMargin, thesis\.base_value, locale\)/);
        assert.doesNotMatch(memo, /pct\(thesis\.margin_of_safety\)/);
    });
});
