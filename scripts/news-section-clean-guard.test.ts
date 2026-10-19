// Guard: la imagen de la tarjeta de Noticias destacadas se acota a 112px en móvil.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/NewsSection.tsx', 'utf8');

test('imagen acotada en móvil', () => {
    assert.ok(SRC.includes('h-28 w-full'));
    assert.ok(!SRC.includes('h-40 w-full'));
});
