/**
 * Validación del formulario "Nueva inversión": ningún submit falla en silencio.
 * Se ejecuta con: node --experimental-strip-types --test scripts/transaction-validation.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';

register('./transaction-validation.loader.mjs', import.meta.url);

// Import dinámico: register() debe ejecutarse antes de resolver el alias @/
// que usa transactionValidation.ts internamente.
// @ts-expect-error entorno de test con node --experimental-strip-types (import con extensión solo en runtime)
const { hasTransactionErrors, validateTransactionForm, TRANSACTION_VALIDATION_ES } = await import('../components/portfolio/transactionValidation.ts');

// Las copias ES por defecto del validador son las del diccionario i18n
// (carril C): si una cambia, cambia la otra.
const esPortfolio = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
describe('transactionValidation: copias ES == diccionario', () => {
  it('cada mensaje por defecto coincide con messages/es/portfolio.json#transactionForm', () => {
    for (const [key, value] of Object.entries(TRANSACTION_VALIDATION_ES)) {
      assert.equal(esPortfolio.transactionForm[key], value, `transactionForm.${key}`);
    }
  });
});
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
const { parseLocalizedNumber } = await import('../lib/format.ts');

const NOW = new Date('2026-09-23T12:00:00');

const VALID = {
  symbol: 'AAPL',
  type: 'buy' as const,
  quantity: '10',
  price: '150',
  date: '2026-09-23',
};

describe('validateTransactionForm (F1: sin submits silenciosos)', () => {
  it('acepta un formulario completo válido', () => {
    assert.deepEqual(validateTransactionForm(VALID, NOW), {});
  });

  it('exige símbolo seleccionado', () => {
    const errors = validateTransactionForm({ ...VALID, symbol: '  ' }, NOW);
    assert.ok(errors.symbol, 'debe pedir seleccionar acción');
    assert.ok(hasTransactionErrors(errors));
  });

  it('rechaza cantidad vacía, cero o negativa', () => {
    for (const quantity of ['', '0', '-5', 'abc']) {
      const errors = validateTransactionForm({ ...VALID, quantity }, NOW);
      assert.ok(errors.quantity, `cantidad ${JSON.stringify(quantity)} debe fallar`);
    }
  });

  it('rechaza precio vacío o negativo', () => {
    for (const price of ['', '-1']) {
      const errors = validateTransactionForm({ ...VALID, price }, NOW);
      assert.ok(errors.price, `precio ${JSON.stringify(price)} debe fallar`);
    }
  });

  it('rechaza fecha inválida o futura', () => {
    assert.ok(validateTransactionForm({ ...VALID, date: '' }, NOW).date);
    assert.ok(validateTransactionForm({ ...VALID, date: '23/09/2026' }, NOW).date);
    assert.ok(validateTransactionForm({ ...VALID, date: '2026-09-24' }, NOW).date);
  });
});

describe('parseLocalizedNumber (decimales con coma es-ES)', () => {
  it('parsea decimales con coma', () => {
    assert.equal(parseLocalizedNumber('12,53'), 12.53);
  });

  it('parsea miles con punto y decimales con coma', () => {
    assert.equal(parseLocalizedNumber('1.234,56'), 1234.56);
  });

  it('parsea formato internacional sin coma', () => {
    assert.equal(parseLocalizedNumber('1234.56'), 1234.56);
  });

  it('nunca trunca en silencio como parseFloat', () => {
    // parseFloat('12,53') === 12 era el bug: una alerta a 12,53 se creaba a 12
    assert.notEqual(parseLocalizedNumber('12,53'), 12);
  });

  it('devuelve null ante entrada inválida', () => {
    assert.equal(parseLocalizedNumber(''), null);
    assert.equal(parseLocalizedNumber('abc'), null);
    assert.equal(parseLocalizedNumber('12,53,1'), null);
  });
});

describe('validateTransactionForm con decimales es-ES', () => {
  it('acepta cantidad y precio con coma decimal', () => {
    assert.deepEqual(validateTransactionForm({ ...VALID, quantity: '2,5', price: '150,75' }, NOW), {});
  });

  it('sigue rechazando letras', () => {
    const errors = validateTransactionForm({ ...VALID, quantity: 'abc' }, NOW);
    assert.ok(errors.quantity);
  });
});
