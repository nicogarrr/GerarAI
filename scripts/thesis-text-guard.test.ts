import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error TS5097: extensión explícita para node strip-types.
import { cleanThesisText } from '../lib/research/thesis-text.ts';

test('claves snake_case no llegan a la prosa de la tesis', () => {
  const out = cleanThesisText('no publicable todavía: faltan addressable_subscribers, monthly_arpu.');
  assert.doesNotMatch(out, /_/);
  assert.match(out, /suscriptores direccionables/);
});

test('decimales largos se formatean y la puntuación doble se corrige', () => {
  assert.equal(cleanThesisText('tipo -0.006019747112082423 acotado'), 'tipo -0,00602 acotado');
  assert.equal(cleanThesisText('ingresos 70918000.000000 USD'), 'ingresos 70.918.000 USD');
  assert.equal(cleanThesisText('Pregunta clave: ¿rampa?.'), 'Pregunta clave: ¿rampa?');
  assert.equal(cleanThesisText('Afecta a 0 claims..'), 'Afecta a 0 claims.');
  assert.equal(cleanThesisText('Seguimiento...'), 'Seguimiento...');
});

test('URLs y números normales no se tocan', () => {
  assert.equal(cleanThesisText('ver https://sec.gov/a_b/c_d y 12,5 % con 3.14'), 'ver https://sec.gov/a_b/c_d y 12,5 % con 3.14');
});
