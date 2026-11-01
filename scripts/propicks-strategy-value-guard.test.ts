/**
 * Guard F151 (selector de estrategia): el valor cerrado muestra el NOMBRE
 * de la estrategia, no un fragmento de su descripción. El SelectValue de
 * Radix pinta por defecto todo el contenido del item (nombre+descripción),
 * así que el valor explícito es obligatorio.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/propicks-strategy-value-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync('components/proPicks/StrategySelector.tsx', 'utf8');

describe('propicks strategy value guard (F151)', () => {
  it('el valor cerrado es el nombre de la estrategia seleccionada', () => {
    assert.match(source, /const selectedOption = options\.find\(\(option\) => option\.id === currentStrategy\)/, 'resuelve la opción seleccionada');
    assert.match(source, /<SelectValue placeholder=\{t\('propicks\.strategySelector\.placeholder'\)\}>\{selectedOption\?\.name\}<\/SelectValue>/, 'SelectValue pinta solo el nombre');
  });

  it('SelectValue no va vacío (volvería a pintar nombre+descripción)', () => {
    assert.equal(source.includes("<SelectValue placeholder={t('propicks.strategySelector.placeholder')} />"), false, 'SelectValue vacío reproduce el bug');
  });

  it('la descripción sigue disponible dentro del desplegable', () => {
    assert.match(source, /\{strategy\.description\}/, 'la descripción no se borra del item');
  });
});
