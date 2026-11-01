/**
 * Guard: el pie de /temas no pinta el proveedor (data.source): es una
 * etiqueta de fuente y la fuente ya viaja en la API. Se conservan la
 * frescura del dato, el metodo y los avisos de calidad (parcial /
 * recalculando).
 * Ejecutar: node --experimental-strip-types --test scripts/temas-pie-sin-fuente-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pagina = readFileSync('app/(root)/temas/page.tsx', 'utf8');

describe('Temas: pie sin etiqueta de fuente', () => {
  it('el pie no pinta data.source', () => {
    const pie = pagina.slice(pagina.indexOf('<footer'), pagina.indexOf('</footer>'));
    assert.doesNotMatch(pie, /data\.source/);
  });
  it('el pie conserva frescura, metodo y avisos de calidad del dato', () => {
    // Los avisos del pie viven en es/themes.json: solo se añade la sección de la página.
    const pie = pagina.slice(pagina.indexOf('<footer'), pagina.indexOf('</footer>'))
      + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/themes.json', 'utf8')).page);
    assert.match(pie, /[Ii]ntradía/);
    assert.match(pie, /formatMarketDate\(data\.as_of\)/);
    assert.match(pie, /data\.method/);
    assert.match(pie, /datos parciales/);
    assert.match(pie, /recalculando: se muestra la última versión calculada/);
  });
  it('la fuente sigue llegando en la API (getMarketThemes conserva el campo)', () => {
    assert.match(pagina, /getMarketThemes\(\)/);
  });
});
