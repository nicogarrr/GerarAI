import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Burbuja del Cerebro (chat global): lleva overflow-hidden por las esquinas
// redondeadas. Sin corte de palabra, un enlace o un token largo quedaba oculto
// a partir del borde (a 390 px se perdía media URL, sin forma de leerla).
// El e2e e2e/mobile-brain-long-message.spec.ts lo mide en el navegador; esta
// guarda lo fija en el código para el bundle de guards.
const SOURCE = readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');

function bubbleBody(): string {
  const start = SOURCE.indexOf('function BrainMessageBubble(');
  assert.ok(start >= 0, 'no encuentro BrainMessageBubble en GlobalBrainPanel.tsx');
  const end = SOURCE.indexOf('\n});', start);
  assert.ok(end > start, 'no encuentro el final de BrainMessageBubble');
  return SOURCE.slice(start, end);
}

const WRAP = /\[overflow-wrap:anywhere\]|\bwrap-anywhere\b|\bbreak-words\b|\bbreak-all\b/;

test('toda caja con overflow-hidden de la burbuja parte las palabras largas', () => {
  const classNames = bubbleBody().match(/className=\{?[`'"][^`'"]*[`'"]/g) ?? [];
  const clipping = classNames.filter((c) => /\boverflow-hidden\b/.test(c));
  assert.ok(clipping.length > 0, 'la burbuja ya no tiene overflow-hidden: revisa esta guarda');
  for (const c of clipping) {
    assert.match(c, WRAP, `burbuja con overflow-hidden sin corte de palabra: ${c}`);
    assert.match(c, /\bmin-w-0\b/, `burbuja flexible sin min-w-0: ${c}`);
  }
});

test('los bloques de código de la respuesta se desplazan dentro de la burbuja', () => {
  const classNames = bubbleBody().match(/className=\{?[`'"][^`'"]*[`'"]/g) ?? [];
  const clipping = classNames.filter((c) => /\boverflow-hidden\b/.test(c));
  for (const c of clipping) {
    assert.match(c, /\[&_pre\]:overflow-x-auto/, `un <pre> se cortaría dentro de: ${c}`);
  }
});
