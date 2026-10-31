/**
 * Guard: la etiqueta de lado de las operaciones insider (Compra/Venta) sale
 * del diccionario i18n en la interfaz, no de literales ES duros. Los
 * literales historicos quedan SOLO como fallback sin t (scripts y llamadas
 * legacy fuera de React). Claves: insider.feed.sideBuyLabel/sideSellLabel.
 * Ejecutar: node --experimental-strip-types --test scripts/insider-side-label-i18n-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const feed = readFileSync('components/insider/InsiderFeed.tsx', 'utf8');
const signals = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');
const format = readFileSync('lib/insider/format.ts', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/insider.json', 'utf8'));
const en = JSON.parse(readFileSync('lib/i18n/messages/en/insider.json', 'utf8'));

describe('Insider: etiqueta de lado internacionalizada', () => {
  it('las claves existen en es (literal historico) y en', () => {
    assert.equal(es.feed.sideBuyLabel, 'Compra');
    assert.equal(es.feed.sideSellLabel, 'Venta');
    assert.equal(en.feed.sideBuyLabel, 'Buy');
    assert.equal(en.feed.sideSellLabel, 'Sell');
  });
  it('InsiderFeed pasa el traductor en ambas apariciones (movil y tabla)', () => {
    const usos = feed.match(/\{sideLabel\(tx\.side, t\)\}/g) ?? [];
    assert.equal(usos.length, 2);
    assert.doesNotMatch(feed, /\{sideLabel\(tx\.side\)\}/);
  });
  it('InsiderSignalsView pasa el traductor a insiderCodeLabel (codigos P/S)', () => {
    assert.match(signals, /\{insiderCodeLabel\(tx\.code, ti\)\}/);
    assert.doesNotMatch(signals, /\{insiderCodeLabel\(tx\.code\)\}/);
  });
  it('sideLabel e insiderCodeLabel aceptan el traductor y usan las claves', () => {
    assert.match(format, /export function sideLabel\(side: string \| null \| undefined, t\?: TranslateFn\)/);
    assert.match(format, /t\('insider\.feed\.sideBuyLabel'\)/);
    assert.match(format, /t\('insider\.feed\.sideSellLabel'\)/);
    assert.match(format, /if \(clean === 'P'\) return sideLabel\('compra', t\)/);
    assert.match(format, /if \(clean === 'S'\) return sideLabel\('venta', t\)/);
  });
});
