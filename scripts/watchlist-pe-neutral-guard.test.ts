/**
 * Guard F144 (PER de /watchlist sin juicio de valoración): la columna
 * PER (TTM) no lleva semáforo. Los umbrales <15 verde / <25 amarillo /
 * resto rojo eran arbitrarios, ciegos al sector y sin leyenda: pintaban
 * de rojo KO 26x, COST 45,9x o ASML 55x - una recomendación implícita
 * en una app que promete «datos, no recomendaciones».
 *
 * Ejecucion: node --experimental-strip-types --test scripts/watchlist-pe-neutral-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');

describe('watchlist PER neutral guard (F144)', () => {
  it('el PER no compara contra umbrales de color', () => {
    assert.equal(page.includes("peRatio < 15"), false, 'umbral <15 eliminado');
    assert.equal(page.includes("peRatio < 25"), false, 'umbral <25 eliminado');
  });

  it('el badge del PER es neutro', () => {
    const badge = page.match(/<Badge variant="outline" className="([^"]*)"[^>]*>\s*\{formatPeRatio/);
    assert.ok(badge, 'badge del PER encontrado');
    assert.ok(!/text-(green|red|yellow|amber)-/.test(badge[1]), `sin color de juicio: ${badge[1]}`);
  });

  it('el cambio de sesión sí conserva su color (signo real, no juicio)', () => {
    assert.match(page, /changePercent >= 0 \? 'text-good' : 'text-bad'/, 'el color por signo usa el par semantico good/bad');
  });
});
