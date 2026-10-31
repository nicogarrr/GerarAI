/**
 * Guard: el pie de /calendar/ipos no lleva etiqueta de fuente (el proveedor
 * viaja en la API y los avisos de degradado nombran al servicio caido, que
 * es calidad del dato). Se conserva la nota de cobertura.
 * Ejecutar: node --experimental-strip-types --test scripts/ipos-pie-sin-fuente-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const es = JSON.parse(readFileSync('lib/i18n/messages/es/calendar.json', 'utf8'));
const en = JSON.parse(readFileSync('lib/i18n/messages/en/calendar.json', 'utf8'));
const pagina = readFileSync('app/(root)/calendar/ipos/page.tsx', 'utf8');

describe('IPOs: pie sin etiqueta de fuente', () => {
  it('el pie no nombra al proveedor ni abre con «Fuente:»', () => {
    for (const footnote of [es.ipos.footnote, en.ipos.footnote]) {
      assert.doesNotMatch(footnote, /fuente|source/i);
      assert.doesNotMatch(footnote, /NASDAQ|EDGAR/i);
    }
  });
  it('la nota de cobertura se conserva en es y en', () => {
    assert.match(es.ipos.footnote, /^Cobertura: solo salidas a bolsa en mercados de EE\. UU\./);
    assert.match(en.ipos.footnote, /^Coverage: only listings on US markets/);
  });
  it('la pagina sigue pintando el pie', () => {
    assert.match(pagina, /ti\('calendar\.ipos\.footnote'\)/);
  });
});
