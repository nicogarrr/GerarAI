import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const ficha = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const indice = readFileSync('app/(root)/research/page.tsx', 'utf8');
const memo = readFileSync('components/research/ThesisMemo.tsx', 'utf8');

// Vocabulario completo de thesis_service._rating: la UI no puede enseñar
// ninguno en crudo (F338: el historial mostraba "expensive" en inglés).
const MOTOR_RATINGS = ['attractive', 'expensive', 'incomplete_price', 'watch', 'blocked', 'insufficient_data'];

test('F338: la ficha cubre todos los ratings del motor de tesis en español', () => {
    for (const rating of MOTOR_RATINGS) {
        assert.match(ficha, new RegExp(`${rating}: '[^']+'`), `ficha sin ${rating}`);
    }
});

test('F338: el indice cubre todos los ratings del motor de tesis en español', () => {
    for (const rating of MOTOR_RATINGS) {
        assert.match(indice, new RegExp(`${rating}: '[^']+'`), `indice sin ${rating}`);
    }
});

test('F338: el memo etiqueta rating y status en vez de mostrarlos en crudo', () => {
    assert.match(memo, /enumLabel\(RATING_LABELS, thesis\.rating\)/);
    assert.match(memo, /enumLabel\(STATUS_LABELS, thesis\.status\)/);
    for (const rating of MOTOR_RATINGS) {
        assert.match(memo, new RegExp(`${rating}: '[^']+'`), `memo sin ${rating}`);
    }
});

test('F343: el memo etiqueta las franjas horarias de catalizadores y nunca las muestra en crudo', () => {
    const KNOWN_SLOTS = ['time-pre-market', 'time-after-hours', 'before-market', 'after-market'];
    for (const slot of KNOWN_SLOTS) {
        assert.match(memo, new RegExp(`'${slot}': '[^']+'`), `memo sin ${slot}`);
    }
    assert.match(memo, /CATALYST_TIME_LABELS\[catalyst\.time\]/, 'memo debe pasar catalyst.time por el mapa');
    assert.doesNotMatch(memo, /` \$\{catalyst\.time\}`/, 'memo no debe renderizar catalyst.time en crudo');
});
