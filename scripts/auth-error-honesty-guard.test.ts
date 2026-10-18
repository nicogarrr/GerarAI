/**
 * Guard: un 401/403 NUNCA se pinta como «sin datos».
 *
 * /taxes (isNotGeneratedYet) e /insider (isUnknownTicker) trataban cualquier
 * 4xx como «esto no existe todavía»: con la sesión caducada (401) o acceso
 * denegado (403) la página mostraba su estado vacío («no tienes nada») en
 * vez de propagar el fallo de autenticación.
 *
 * Ejecución: node --experimental-strip-types --test scripts/auth-error-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { AppError, AuthenticationError, AuthorizationError, NotFoundError, isAuthError } from '../lib/types/errors.ts';

const taxes = readFileSync('app/(root)/taxes/page.tsx', 'utf8');
const insider = readFileSync('app/(root)/insider/page.tsx', 'utf8');

describe('isAuthError', () => {
    it('reconoce 401 y 403, y solo esos', () => {
        assert.equal(isAuthError(new AuthenticationError()), true);
        assert.equal(isAuthError(new AuthorizationError()), true);
        assert.equal(isAuthError(new NotFoundError()), false);
        assert.equal(isAuthError(new AppError('boom', 'X', 422)), false);
        assert.equal(isAuthError(new AppError('boom', 'X', 500)), false);
        assert.equal(isAuthError(new Error('plain')), false);
        assert.equal(isAuthError(null), false);
    });
});

describe('taxes: el 4xx «sin generar» excluye 401/403', () => {
    it('isNotGeneratedYet no cubre auth', () => {
        assert.match(taxes, /statusCode >= 400 && error\.statusCode < 500 && !isAuthError\(error\)/);
    });
    it('un error de auth de cualquier lectura se propaga antes del estado vacío', () => {
        assert.match(taxes, /if \(authError\) throw authError;/);
        // El throw va ANTES de convertir los errores en holdings=[] / report=null.
        const throwAt = taxes.indexOf('if (authError) throw authError;');
        const emptyAt = taxes.indexOf('const holdings = holdingsError ? [] : holdingsRead.value;');
        assert.ok(throwAt !== -1 && emptyAt !== -1 && throwAt < emptyAt);
    });
});

describe('insider: el 4xx «ticker desconocido» excluye 401/403', () => {
    it('isUnknownTicker no cubre auth', () => {
        assert.match(insider, /statusCode >= 400 && error\.statusCode < 500 && !isAuthError\(error\)/);
        // Lo que no es ticker desconocido se relanza (incluye 401/403 ahora).
        assert.match(insider, /if \(!isUnknownTicker\(error\)\) throw error;/);
    });
});
