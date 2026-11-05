import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// Medido en prod (5-nov-2026, petición de Nico): el índice /research carga
// en >10 s y dispara 18 peticiones _rsc de prefetch (una por tarjeta en
// viewport), cada una un render RSC completo de la ficha — la vista más cara
// del frontend, con varios workspaces de backend. Mismo arreglo que las
// pestañas de la ficha (#4657): prefetch={false} en la tarjeta.
const source = readFileSync('app/(root)/research/page.tsx', 'utf8');

test('las tarjetas del índice /research no prefetchean la ficha (cada _rsc es un render de ficha completo)', () => {
    const cardLink = source.match(/<Link[\s\S]*?href=\{`\/research\/\$\{encodeURIComponent\(company\.ticker\)\}`\}[\s\S]*?>/);
    assert.ok(cardLink, 'enlace de tarjeta no encontrado');
    assert.match(cardLink[0], /prefetch=\{false\}/);
});
