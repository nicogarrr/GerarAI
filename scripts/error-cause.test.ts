/**
 * Test de clasificación de causas de error (stale/offline/negocio) y
 * traducciones al español.
 *
 * Ejecución: node --experimental-strip-types --test scripts/error-cause.test.ts
 * (node:test estándar, sin red ni dependencias nuevas).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    AuthenticationError,
    classifyError,
    DuplicateError,
    getFriendlyErrorMessage,
    isNextRedirectError,
    ValidationError,
// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types en runtime
} from '../lib/types/errors.ts';

describe('stale-after-redeploy markers', () => {
    const staleMessages = [
        'Failed to find Server Action "abc123". This request might be from an older deployment.',
        'The action could not be found. Please reload the page.',
        'Loading chunk 123 failed after deploy',
        'ChunkLoadError: Loading chunk app/screeners/page failed',
        'Revision mismatch: client bundle is outdated',
        'Data is stale, refetch required',
    ];
    for (const message of staleMessages) {
        it(`clasifica como stale: ${message.slice(0, 48)}…`, () => {
            assert.equal(classifyError(new Error(message)), 'stale');
        });
    }
});

describe('orden stale-antes-que-offline', () => {
    it('un mensaje con marcador stale y genérico offline sigue siendo stale', () => {
        // Contiene "server action" (marcador genérico offline) + marcador stale.
        const error = new Error('Failed to find Server Action abc: fetch failed during prerender');
        assert.equal(classifyError(error), 'stale');
    });

    it('un mensaje genérico de server components sin marcador stale es offline', () => {
        const error = new Error('An error occurred in the Server Components render');
        assert.equal(classifyError(error), 'offline');
    });
});

describe('motor de análisis caído vía server action', () => {
    // lib/research/client.ts lanza ExternalAPIError con este texto; al cruzar
    // la frontera de una server action llega como Error plano (sin code) y la
    // clasificación depende solo de los marcadores. Antes el mensaje crudo en
    // inglés con la ruta interna terminaba en el toast (visto en /alerts).
    const rawMessages = [
        'Research engine unavailable for /api/alerts/rules?active=true (fetch fallido); reintenta en unos segundos.',
        'Research engine unavailable for /api/home (timeout de 15000 ms); reintenta en unos segundos.',
        'Research engine unavailable for /api/watchlist (cancelado por el llamador); reintenta en unos segundos.',
    ];
    for (const message of rawMessages) {
        it(`clasifica offline: ${message.slice(0, 52)}…`, () => {
            assert.equal(classifyError(new Error(message)), 'offline');
        });
        it('el toast sale en español, sin ruta interna', () => {
            const friendly = getFriendlyErrorMessage(new Error(message));
            assert.equal(friendly, 'El motor de análisis no responde ahora mismo. Reintenta en unos segundos.');
            assert.ok(!friendly.includes('/api/'));
        });
    }
});

describe('offline markers', () => {
    const offlineMessages = [
        'fetch failed',
        'Failed to fetch market data',
        'TypeError: NetworkError when attempting to fetch resource',
        'Load failed',
        'connect ECONNREFUSED 127.0.0.1:8000',
        'request ETIMEDOUT',
        'read ECONNRESET',
        'getaddrinfo ENOTFOUND api.example.com',
        'socket hang up',
    ];
    for (const message of offlineMessages) {
        it(`clasifica como offline: ${message.slice(0, 48)}…`, () => {
            assert.equal(classifyError(new Error(message)), 'offline');
        });
    }
});

describe('errores de negocio (AppError)', () => {
    it('validation', () => {
        assert.equal(classifyError(new ValidationError('Fórmula no válida', 'formula')), 'validation');
    });

    it('auth', () => {
        assert.equal(classifyError(new AuthenticationError()), 'auth');
    });

    it('duplicate por código y por mensaje', () => {
        assert.equal(classifyError(new DuplicateError()), 'duplicate');
        assert.equal(classifyError(new Error('Ticker already exists in watchlist')), 'duplicate');
        assert.equal(classifyError(new Error('Ya existe esta alerta')), 'duplicate');
    });
});

describe('traducciones al español', () => {
    it('stale pide recargar', () => {
        const message = getFriendlyErrorMessage(new Error('Loading chunk 4 failed'));
        assert.equal(message, 'Hay una nueva versión de la app: recarga la página.');
    });

    it('offline habla del motor', () => {
        const message = getFriendlyErrorMessage(new Error('fetch failed'));
        assert.match(message, /motor de análisis/i);
        assert.ok(!/fetch failed/i.test(message), 'no debe filtrar inglés crudo');
    });

    it('auth se traduce', () => {
        const message = getFriendlyErrorMessage(new AuthenticationError());
        assert.equal(message, 'Necesitas iniciar sesión para continuar.');
    });

    it('duplicate usa el mensaje específico si se pasa', () => {
        const message = getFriendlyErrorMessage(new DuplicateError(), {
            duplicateMessage: 'Ya tienes esta alerta configurada.',
        });
        assert.equal(message, 'Ya tienes esta alerta configurada.');
    });

    it('validation conserva el mensaje de negocio', () => {
        const message = getFriendlyErrorMessage(new ValidationError('Fórmula no válida'));
        assert.equal(message, 'Fórmula no válida');
    });
});

describe('isNextRedirectError', () => {
    it('detecta el digest NEXT_REDIRECT', () => {
        const redirect = Object.assign(new Error('NEXT_REDIRECT'), {
            digest: 'NEXT_REDIRECT;push;/login;307;',
        });
        assert.equal(isNextRedirectError(redirect), true);
    });

    it('un error normal no es redirect', () => {
        assert.equal(isNextRedirectError(new Error('fetch failed')), false);
        assert.equal(isNextRedirectError(null), false);
        assert.equal(isNextRedirectError('NEXT_REDIRECT'), false);
    });
});
