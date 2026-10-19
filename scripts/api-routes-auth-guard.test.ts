/**
 * Toda route handler de app/api exige sesión: sin ella responde 401 antes de
 * validar entrada, leer parámetros o llamar al backend. La excepción es el
 * catch-all de better-auth, que es quien abre la sesión.
 * Ejecución: node --experimental-strip-types --test scripts/api-routes-auth-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const API = join(root, 'app', 'api');
// Excepciones documentadas:
// - auth catch-all: es quien abre la sesión.
// - calendar-feed: feed ICS público por token opaco (las apps de calendario
//   no tienen sesión); sus propiedades se auditan en el describe de abajo.
const PUBLIC_ROUTES = new Set(['app/api/auth/[...all]/route.ts', 'app/api/calendar-feed/[token]/route.ts']);

function routes(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) return routes(full);
        return name === 'route.ts' ? [full] : [];
    });
}

const files = routes(API).map((full) => ({ rel: relative(root, full).split('\\').join('/'), source: readFileSync(full, 'utf8') }));

describe('app/api/**/route.ts exige sesión (401 sin ella)', () => {
    it('hay rutas que auditar', () => {
        assert.ok(files.length >= 8, `solo ${files.length} route.ts`);
    });

    for (const { rel, source } of files.filter((f) => !PUBLIC_ROUTES.has(f.rel))) {
        it(`${rel}: requireAuthenticatedUser antes de cualquier otra lectura`, () => {
            const start = source.indexOf('async function');
            assert.ok(start >= 0, 'no se encuentra el handler');
            const body = source.slice(start);
            const auth = body.indexOf('await requireAuthenticatedUser()');
            assert.ok(auth >= 0, 'no llama a requireAuthenticatedUser');
            const firstUse = body.search(/await params|request\.json\(|NextResponse\.json|fetch\(|researchIdentityHeaders\(/);
            assert.ok(firstUse < 0 || auth < firstUse, 'la autenticación va después de leer parámetros, validar o llamar al backend');
        });

        it(`${rel}: un fallo de sesión sale como 401, no como 500`, () => {
            const wrapped = /export const (GET|POST|PUT|PATCH|DELETE) = withAuthErrors\(/.test(source);
            const manual401 = /catch[\s\S]{0,200}status: 401/.test(source);
            assert.ok(wrapped || manual401, 'ni withAuthErrors ni catch con 401');
        });
    }
});

describe('excepción pública app/api/calendar-feed: propiedades exigidas', () => {
    const rel = 'app/api/calendar-feed/[token]/route.ts';
    const source = files.find((f) => f.rel === rel)?.source ?? '';

    it('existe y no usa sesión, cookies ni cabeceras de usuario', () => {
        assert.ok(source, 'falta la ruta pública del feed');
        assert.doesNotMatch(source, /requireAuthenticatedUser|withAuthErrors|cookies\(|headers\(\)/);
    });

    it('valida el token con el formato exacto del backend (gfc_ + 43 urlsafe)', () => {
        assert.match(source, /\^gfc_\[A-Za-z0-9_-\]\{43\}\\\.ics\$/);
    });

    it('no reenvía cabeceras del cliente al backend', () => {
        assert.doesNotMatch(source, /request\.headers|headers:\s*request/);
    });

    it('solo el 404 upstream es 404; 5xx/401/red son 502/503', () => {
        assert.match(source, /upstream\.status === 404/);
        assert.match(source, /status: 502/);
        assert.match(source, /status: 503/);
    });

    it('sirve con X-Robots-Tag noindex y Referrer-Policy no-referrer', () => {
        assert.match(source, /'X-Robots-Tag': 'noindex'/);
        assert.match(source, /'Referrer-Policy': 'no-referrer'/);
    });
});
