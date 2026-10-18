import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import { getSafeErrorMessage } from '../lib/types/errors.ts';

// Auditoría lista 9.3: mensajes de error crudos al cliente. Los errores de
// fetch llevan la URL completa del proveedor (?token=...) en el message;
// sin redacción la clave del servidor llegaba al navegador.
// Contrato: las rutas que devuelven `error` al cliente pasan por
// getSafeErrorMessage (redacta vía lib/upstream/redact).

test('getSafeErrorMessage redacta credenciales en URLs de error de fetch', () => {
    const err = new TypeError(
        'fetch failed: GET https://finnhub.io/api/v1/quote?symbol=AAPL&token=secreto123 500'
    );
    const msg = getSafeErrorMessage(err);
    assert.ok(!msg.includes('secreto123'), 'la key no llega al cliente');
    assert.match(msg, /token=REDACTED/);
});

test('getSafeErrorMessage redacta userinfo de DSN y preserva el resto del mensaje', () => {
    const msg = getSafeErrorMessage(new Error('connect redis://default:pw-larga-99@redis.internal:6379 falló'));
    assert.ok(!msg.includes('pw-larga-99'));
    assert.match(msg, /falló/);
});

test('getSafeErrorMessage conserva mensajes de negocio (AppError) y strings', () => {
    assert.equal(getSafeErrorMessage(new Error('Invalid email or password')), 'Invalid email or password');
    assert.equal(getSafeErrorMessage('texto plano'), 'texto plano');
    assert.equal(getSafeErrorMessage(42), 'An unknown error occurred');
});

test('las rutas auditadas no devuelven error.message crudo al cliente', () => {
    const backtest = readFileSync('lib/actions/propicks-backtest.actions.ts', 'utf8');
    assert.doesNotMatch(backtest, /error instanceof Error \? error\.message : String\(error\)/);
    assert.match(backtest, /return \{ error: getSafeErrorMessage\(error\) \};/);

    const auth = readFileSync('lib/actions/auth.actions.ts', 'utf8');
    const unsafe = auth.match(/error: getErrorMessage\(error\)|errorMessage = getErrorMessage\(error\)/g) ?? [];
    assert.equal(unsafe.length, 0, 'auth.actions pasa todo por getSafeErrorMessage');

    const research = readFileSync('lib/actions/research.actions.ts', 'utf8');
    assert.doesNotMatch(research, /error: getErrorMessage\(error\)/);
    assert.match(research, /error: getSafeErrorMessage\(error\)/);
});
