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
  it('los códigos Form 4 no P/S tienen clave i18n en es y en', () => {
    const codes = ['A', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'M', 'O', 'U', 'W', 'X'];
    for (const c of codes) {
      assert.equal(typeof es.feed.codeLabels[c], 'string', `es ${c}`);
      assert.equal(typeof en.feed.codeLabels[c], 'string', `en ${c}`);
      assert.notEqual(es.feed.codeLabels[c], en.feed.codeLabels[c], `es/en ${c} no deben coincidir`);
    }
    assert.equal(es.feed.codeLabels.A, 'Concesión');
    assert.equal(en.feed.codeLabels.A, 'Grant or award');
    assert.equal(es.feed.codeLabels.M, 'Ejercicio de opción');
    assert.equal(en.feed.codeLabels.M, 'Option exercise');
    assert.equal(es.feed.codeUnknown, 'Código {code}');
    assert.equal(en.feed.codeUnknown, 'Code {code}');
  });
  it('la ficha etiqueta el código con insiderCodeLabel y el traductor (sin código crudo)', () => {
    const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
    assert.match(page, /\{insiderCodeLabel\(tx\.code, t\)\}/);
    assert.doesNotMatch(page, /tx\.code \?\? '—'/);
    assert.match(page, /import \{ insiderCodeLabel, insiderName, insiderRole \} from '@\/lib\/insider\/format';/);
  });
  it('fichaTxBuy/fichaTxSell se retiran al quedar sin uso (sin huérfanas nuevas)', () => {
    const resEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8'));
    const resEn = JSON.parse(readFileSync('lib/i18n/messages/en/research.json', 'utf8'));
    assert.equal(resEs.fichaTxBuy, undefined);
    assert.equal(resEs.fichaTxSell, undefined);
    assert.equal(resEn.fichaTxBuy, undefined);
    assert.equal(resEn.fichaTxSell, undefined);
  });
  it('insiderCodeLabel con t traduce por clave; sin t mantiene el legacy es', async () => {
    const { insiderCodeLabel: label } = await import('../lib/insider/format.ts');
    const en = (p, vars) =>
      p === 'insider.feed.codeLabels.A' ? 'Grant or award'
        : p === 'insider.feed.codeLabels.M' ? 'Option exercise'
          : p === 'insider.feed.codeUnknown' ? `Code ${vars.code}`
            : p;
    assert.equal(label('A', en), 'Grant or award');
    assert.equal(label('m', en), 'Option exercise');
    assert.equal(label('Z', en), 'Code Z');
    assert.equal(label('A'), 'Concesión');
    assert.equal(label('Z'), 'Código Z');
    assert.equal(label(''), '—');
  });
  it('sideLabel e insiderCodeLabel aceptan el traductor y usan las claves', () => {
    assert.match(format, /export function sideLabel\(side: string \| null \| undefined, t\?: TranslateFn\)/);
    assert.match(format, /t\('insider\.feed\.sideBuyLabel'\)/);
    assert.match(format, /t\('insider\.feed\.sideSellLabel'\)/);
    assert.match(format, /if \(clean === 'P'\) return sideLabel\('compra', t\)/);
    assert.match(format, /if \(clean === 'S'\) return sideLabel\('venta', t\)/);
  });
});
