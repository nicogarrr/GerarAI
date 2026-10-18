/**
 * F22: /research mostraba "Salud 100/100" junto a "requiere revisión" sin
 * decir por que. El estado sale de revisiones o alertas abiertas: la tarjeta
 * ahora las cuenta; sin pendientes no se inventa texto.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { openReviewsLabel } from '../lib/labels.ts';

test('cuenta revisiones y alertas abiertas', () => {
    assert.equal(openReviewsLabel({ open_reviews: 1, open_alerts: 0 }), '1 revisión abierta');
    assert.equal(
        openReviewsLabel({ open_reviews: 2, open_alerts: 3 }),
        '2 revisiones abiertas · 3 alertas abiertas',
    );
});

test('sin pendientes o sin datos no inventa texto', () => {
    assert.equal(openReviewsLabel({ open_reviews: 0, open_alerts: 0 }), null);
    assert.equal(openReviewsLabel(null), null);
});

test('la tarjeta del índice usa el contador', () => {
    const page = readFileSync('app/(root)/research/page.tsx', 'utf8');
    assert.match(page, /openReviewsLabel\(snapshot\.counts\)/);
});

test('la tarjeta conserva el motivo no valorable y muestra pendientes aparte', () => {
    const page = readFileSync('app/(root)/research/page.tsx', 'utf8');
    assert.match(page, />No valorable: falta evidencia<\/span>/);
    assert.match(page, /\{pending \? <span[^>]*>\{pending\}<\/span> : null\}/);
});
