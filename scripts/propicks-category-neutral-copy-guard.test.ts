/**
 * Guard del copy MEDIDO de las categorías del embudo (components/proPicks/
 * category-display.ts) y de su uso en la caja «Sobre ProPicks IA».
 *
 * Antes la caja afirmaba en literal «Valoración y momentum: neutras en los picks
 * actuales sin datos», una afirmación fija sobre un run concreto: el día que el
 * embudo trajera CFROI/WACC o momentum, el copy seguiría mintiendo, y un
 * «faltan» insinúa una cobertura que nadie va a completar. Ahora la frase se
 * deriva de los picks.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-category-neutral-copy-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { CATEGORY_KEYS, categoryNeutralNote, CATEGORY_NEUTRAL_CAUSE } from '../components/proPicks/category-display.ts';

const cards = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');

describe('copy de categorías ProPicks derivado del run (no literal)', () => {
  it('sin picks no se afirma nada', () => {
    assert.equal(categoryNeutralNote(['value', 'momentum'], 0), null);
  });

  it('ninguna categoría neutra: las seis puntúan con datos', () => {
    const note = categoryNeutralNote([], 12);
    assert.ok(note);
    assert.equal(note.marker, '✓');
    assert.equal(note.neutralKeys.length, 0);
    assert.match(note.text, /6 categorías del embudo tienen datos en los 12 picks de este run/);
  });

  it('categorías neutras: se nombran, se dice el número de picks y la causa real', () => {
    const note = categoryNeutralNote(['value', 'momentum'], 20);
    assert.ok(note);
    assert.equal(note.marker, '~');
    assert.deepEqual(note.neutralKeys, ['value', 'momentum']);
    assert.match(note.text, /Valoración, Momentum: sin datos en los 20 picks de este run/);
    // La causalidad es la del embudo: CFROI+WACC para valoración, serie de
    // precios para momentum (no al revés).
    assert.match(note.text, /sin CFROI y WACC por empresa/);
    assert.match(note.text, /sin la serie de precios de 12 meses/);
    // El 50 se declara explícitamente como «sin dato», no como score.
    assert.match(note.text, /el 50 es «sin dato», no un score/);
  });

  it('una categoría neutra cualquiera nombra su entrada, sin inventar cobertura', () => {
    const note = categoryNeutralNote(['debtLiquidity'], 5);
    assert.ok(note);
    assert.match(note.text, /Deuda y liquidez: sin datos en los 5 picks/);
    assert.match(note.text, /no aplica a bancos/);
  });

  it('las seis causas son las métricas que el embudo lee de verdad', () => {
    assert.equal(CATEGORY_KEYS.length, 6);
    for (const key of CATEGORY_KEYS) {
      assert.ok(CATEGORY_NEUTRAL_CAUSE[key].length > 0, `${key} sin causa declarada`);
    }
  });

  it('la caja deriva la frase del run y solo cae al límite conocido sin picks', () => {
    assert.match(cards, /import \{ CATEGORY_KEYS, categoryNeutralNote \} from '\.\/category-display';/);
    assert.match(
      cards,
      /categoryNeutralNote\(CATEGORY_KEYS\.filter\(\(key\) => allNeutralCategory\(picks, key\)\), picks\.length, locale\)/,
    );
    assert.match(cards, /\{neutralNote\.marker\} \{neutralNote\.text\}/);
    // El bloque «Sobre ProPicks IA» se eliminó: queda solo la línea medida.
    assert.ok(!cards.includes('Sobre ProPicks IA'));
    assert.ok(!cards.includes('~ Valoración y momentum: neutras en los picks actuales sin datos'));
  });

  it('la línea medida sigue declarando el 50 como ausencia de dato', () => {
    const note = categoryNeutralNote(['value'], 3);
    assert.ok(note && /el 50 es «sin dato», no un score/.test(note.text));
  });
});