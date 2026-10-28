/**
 * Guard: /temas pagina la lista de temas con ?pagina=N (enlaces reales, sin
 * scroll infinito) y los enlaces de ticker de las tablas miden >= 44 px.
 * Ejecutar: node --experimental-strip-types --test scripts/temas-paginacion-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pagina = readFileSync('app/(root)/temas/page.tsx', 'utf8');

describe('Temas: paginacion y objetivos tactiles', () => {
  it('la pagina corta la lista con paginateThemes y pinta nav con enlaces prev/next', () => {
    assert.match(pagina, /paginateThemes\(sortedThemes, requestedPage\)/);
    assert.match(pagina, /aria-label="Paginación de temas"/);
    assert.match(pagina, /rel="prev"/);
    assert.match(pagina, /rel="next"/);
  });
  it('no hay scroll infinito ni observer en la pagina', () => {
    assert.doesNotMatch(pagina, /IntersectionObserver|onScroll|useInfinite/);
  });
  it('el ticker de la tabla es un objetivo de 44 px', () => {
    assert.match(pagina, /inline-flex min-h-11[^"]*items-center[^"]*text-teal-300[^"]*"\s+href=\{`\/research\/\$\{row\.ticker\}`\}/);
  });
});
