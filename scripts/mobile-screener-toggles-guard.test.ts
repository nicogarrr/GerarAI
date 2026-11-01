import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: los conmutadores segmentados de screeners respetan el área táctil
 * de 44px en móvil (medido a 390px, 2026-10-31):
 * - "Tipo de comparación" (Valor/Métrica): py-1.5 + text-xs = 28px reales.
 * - "Orden" (Mayor/Menor primero): min-h-9 = 36px.
 * Convención de la casa: min-h-11 en móvil, altura compacta en sm+.
 */

const SRC = 'components/screeners/FilterFields.tsx';

test('conmutador Valor/Métrica con área táctil 44px en móvil', () => {
    const src = readFileSync(SRC, 'utf8');
    const i = src.indexOf("aria-label={t('screener.comparisonTypeAria')}");
    assert.ok(i >= 0, 'radiogroup Tipo de comparación existe');
    const bloque = src.slice(i, i + 700);
    assert.ok(bloque.includes('min-h-11'), 'Valor/Métrica con min-h-11 en móvil');
    assert.ok(bloque.includes('sm:min-h-0'), 'Valor/Métrica conserva altura compacta en sm+');
    assert.ok(bloque.includes('items-center justify-center'), 'Valor/Métrica centrado como el conmutador Orden');
});

test('conmutador Orden con área táctil 44px en móvil', () => {
    const src = readFileSync(SRC, 'utf8');
    const i = src.indexOf("aria-label={t('screener.orderLabel')}");
    assert.ok(i >= 0, 'radiogroup Orden existe');
    const bloque = src.slice(i, i + 700);
    assert.ok(bloque.includes('min-h-11'), 'Orden con min-h-11 en móvil');
    assert.ok(bloque.includes('sm:min-h-9'), 'Orden conserva min-h-9 en sm+');
});
