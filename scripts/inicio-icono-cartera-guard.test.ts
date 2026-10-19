// Guard: la caja del icono de «Tu cartera en una línea» no se estira a todo
// el ancho en móvil (flex-col con align stretch): self-start la mantiene redonda.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('la caja del icono no se estira en móvil', () => {
    assert.ok(SRC.includes('bg-teal-500/10 rounded-full shrink-0 self-start'));
});
