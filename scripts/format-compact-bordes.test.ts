/**
 * Bordes de formatCompact (auditoría de fórmulas, fase 2). Fuente: ECMA-402
 * Intl.NumberFormat «compact»: la escala se decide sobre la cifra redondeada.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error Node type stripping requires the extension.
import { formatCompact } from '../lib/format.ts';

const norm = (s: string) => s.replace(/\u00a0|\u202f/g, ' ');

test('999.999.999 es «1 mil M», no «1.000 M»', () => {
    assert.equal(norm(formatCompact(999_999_999)), '1 mil M');
    assert.equal(norm(formatCompact(-999_999_999)), '-1 mil M');
    assert.equal(norm(formatCompact(999_994_999)), '999,99 M');
});

test('las cifras normales no cambian', () => {
    assert.equal(norm(formatCompact(200_966_000_000)), '200,97 mil M');
    assert.equal(norm(formatCompact(24_000_000)), '24 M');
});

test('propiedad: nunca «1.000 M» (200 casos con semilla fija)', () => {
    let state = 404;
    const rand = () => ((state = (Math.imul(state, 1664525) + 1013904223) >>> 0) / 2 ** 32);
    for (let k = 0; k < 200; k++) {
        const value = (0.999 + rand() * 0.002) * 1e9;
        assert.ok(!norm(formatCompact(value)).startsWith('1.000 M'), formatCompact(value));
    }
});
