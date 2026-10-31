/**
 * Guard: los tooltips de precios objetivo de analistas y la nota de Canada
 * en /insider no pintan el proveedor (etiqueta de fuente; la fuente sigue
 * viajando en la API). Se conservan el caracter no oficial, el detalle por
 * firma, la hora y la conversion de divisa.
 * Ejecutar: node --experimental-strip-types --test scripts/analistas-tooltip-sin-fuente-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const componente = readFileSync('components/common/AnalystTargetLine.tsx', 'utf8');
const esUi = JSON.parse(readFileSync('lib/i18n/messages/es/ui.json', 'utf8'));
const enUi = JSON.parse(readFileSync('lib/i18n/messages/en/ui.json', 'utf8'));
const esInsider = JSON.parse(readFileSync('lib/i18n/messages/es/insider.json', 'utf8'));
const enInsider = JSON.parse(readFileSync('lib/i18n/messages/en/insider.json', 'utf8'));
const esPortfolio = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
const enPortfolio = JSON.parse(readFileSync('lib/i18n/messages/en/portfolio.json', 'utf8'));

describe('Analistas: tooltips sin etiqueta de fuente', () => {
  it('el title no pinta data.source y declara el caracter no oficial', () => {
    const linea = componente.split('\n').find((l) => l.includes('const title ='));
    assert.ok(linea, 'title no encontrado');
    assert.doesNotMatch(linea, /data\.source/);
    assert.match(linea, /ui\.analystTargets\.notOfficial/);
    assert.match(linea, /firmsNote/);
    assert.match(linea, /fetchedNote/);
    assert.match(linea, /mismatchNote/);
  });
  it('la clave notOfficial existe en es y en', () => {
    assert.equal(esUi.analystTargets.notOfficial, 'Fuente no oficial');
    assert.equal(enUi.analystTargets.notOfficial, 'Unofficial source');
  });
  it('el title de la columna en cartera no nombra al proveedor', () => {
    for (const value of [esPortfolio.holdings.analystTitle, enPortfolio.holdings.analystTitle]) {
      assert.doesNotMatch(value, /Yahoo|Finnhub|FMP/i);
      assert.match(value, /no oficial|not official|Unofficial/i);
    }
  });
  it('Canada conserva no oficial y SEDI sin nombrar al proveedor', () => {
    assert.equal(esInsider.feed.canadaSourcePre, 'Fuente no oficial; la verdad oficial es ');
    assert.equal(enInsider.feed.canadaSourcePre, 'Unofficial source; the official record is ');
    assert.doesNotMatch(esInsider.feed.canadaSourcePre + enInsider.feed.canadaSourcePre, /Yahoo/i);
  });
  it('el badge de Canada (movil y escritorio) tampoco nombra al proveedor', () => {
    assert.equal(esInsider.feed.canadaBadge, 'Canadá · fuente no oficial');
    assert.equal(enInsider.feed.canadaBadge, 'Canada · unofficial source');
  });
});
