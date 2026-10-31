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

// Decisión de Nico (2026-10-20, revisión de diseño del índice /research):
// contadores de pendientes FUERA de las tarjetas (una tarjeta = un solo
// estado; el contador de revisiones/alertas generaba señales contradictorias
// tipo «cobertura 100/100 + ámbar») y /research/data-health se elimina entera.
// Se conserva el motivo de no valorable, en gris neutro (sin ámbar), para no
// suavizar la causa.
test('la tarjeta del índice no usa contadores de pendientes', () => {
    const page = readFileSync('app/(root)/research/page.tsx', 'utf8');
    assert.doesNotMatch(page, /openReviewsLabel\(snapshot\.counts\)/);
});

test('la tarjeta conserva el motivo no valorable en gris neutro', () => {
    const page = readFileSync('app/(root)/research/page.tsx', 'utf8');
    assert.match(page, /<span[^>]*text-gray-500[^>]*>\s*\{t\('research\.notValuable'\)\}\s*<\/span>/);
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).notValuable, 'No valorable: falta evidencia');
    assert.doesNotMatch(page, /notValuable'\)\}<\/span>.{0,120}amber/);
    assert.doesNotMatch(page, /\{pending \? <span[^>]*>\{pending\}<\/span> : null\}/);
});
