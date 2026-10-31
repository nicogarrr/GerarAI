/**
 * Guard: el pie de la sección 8-K del calendario macro dice lo que hay.
 *
 * Tester 6 (2026-10-19): las tarjetas decían «Sin texto completo disponible»
 * mientras el pie prometía «Extractos literales del 8-K». Contrato: el pie
 * solo promete extractos literales cuando hay alguno; con mezcla lo matiza
 * («cuando el texto completo está disponible») y sin extractos lo dice.
 * La ingesta no cambia: la decisión de producto sobre 8-K sin texto completo
 * sigue pendiente.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/macro-calendar-8k-pie-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/macro-calendar/page.tsx', 'utf8');
// Las cadenas visibles viven en el diccionario i18n (carril C); la página
// las referencia por clave. El guard verifica ambos extremos.
const esMacro = JSON.parse(readFileSync('lib/i18n/messages/es/calendar.json', 'utf8')).macro;

describe('Calendario macro: el pie de 8-K refleja si hay extractos', () => {
  it('el pie se condiciona a que existan extractos', () => {
    assert.match(
      page,
      /digest\.items\.some\(\(entry\) => entry\.items\.length > 0\)/,
      'el pie ya no puede prometer extractos cuando no los hay',
    );
  });

  it('el texto íntegro solo sale cuando TODAS las tarjetas tienen extractos', () => {
    assert.match(page, /digest\.items\.every\(\(entry\) => entry\.items\.length > 0\)/);
    assert.ok(page.includes('calendar.macro.excerptsAll'));
    assert.equal(esMacro.excerptsAll, 'Extractos literales del 8-K, en inglés. Sin cifras recalculadas.');
    assert.ok(page.includes('calendar.macro.excerptsSome'));
    assert.match(esMacro.excerptsSome, /cuando el texto completo está disponible/);
  });

  it('sin extractos el pie lo dice y remite al documento oficial', () => {
    assert.ok(page.includes('calendar.macro.excerptsNone'));
    assert.match(esMacro.excerptsNone, /^Sin extractos: el texto completo de estos 8-K no estaba disponible/);
  });
});
