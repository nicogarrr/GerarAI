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
// - health: sonda de vida pública a propósito (balanceador y monitorización);
//   respuesta constante sin sesión, DB, secretos ni llamadas a terceros.
// - [...rest]: 404 de rutas de API inexistentes; respuesta constante que no
//   revela nada, y exigir sesión diría 401 de algo que ni existe.
// - admin/approvals y admin/approvals/decide: Nico llega desde el correo, sin
//   sesión; los protege el token HMAC de un solo uso firmado con
//   BETTER_AUTH_SECRET (ver lib/auth/account-approval.ts), no una cookie.
//   Sus propiedades se auditan en el describe de abajo.
const PUBLIC_ROUTES = new Set([
    'app/api/auth/[...all]/route.ts',
    'app/api/calendar-feed/[token]/route.ts',
    'app/api/health/route.ts',
    'app/api/[...rest]/route.ts',
    'app/api/admin/approvals/route.ts',
    'app/api/admin/approvals/decide/route.ts',
]);

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

describe('excepciones públicas app/api/admin/approvals: propiedades exigidas', () => {
    for (const rel of ['app/api/admin/approvals/route.ts', 'app/api/admin/approvals/decide/route.ts']) {
        const source = files.find((f) => f.rel === rel)?.source ?? '';
        it(`${rel}: existe, verifica el token HMAC y no usa sesión ni cookies`, () => {
            assert.ok(source, `falta la ruta pública ${rel}`);
            assert.match(source, /verify(AdminList|Decision)Token\(/);
            assert.doesNotMatch(source, /requireAuthenticatedUser|cookies\(|headers\(\)/);
        });
        it(`${rel}: sin caché y sin estado compartido (force-dynamic)`, () => {
            // La página HTML sale por el helper compartido (approval-page.ts):
            // el no-store se audita allí una sola vez.
            assert.match(source, /approvalPage\(/, 'la página HTML sale por el helper compartido');
            const helper = readFileSync(join(root, 'lib', 'auth', 'approval-page.ts'), 'utf8');
            assert.match(helper, /Cache-Control': 'no-store'/);
            assert.match(source, /export const dynamic = 'force-dynamic'/);
        });
    }
    it('decide: GET solo confirma; POST decide PRIMERO (con fence) y aplica después', () => {
        const source = files.find((f) => f.rel === 'app/api/admin/approvals/decide/route.ts')?.source ?? '';
        assert.match(source, /export async function GET/);
        assert.match(source, /export async function POST/);
        const getBody = source.slice(source.indexOf('export async function GET'), source.indexOf('export async function POST'));
        const postBody = source.slice(source.indexOf('export async function POST'));
        // GET no escribe nada (los escáneres de correo precargan enlaces).
        assert.doesNotMatch(getBody, /findOneAndUpdate|updateOne|deleteMany/);
        // POST: claim atómico (decidedAt:null + processingAt) con fence
        // aleatorio (claimId); finalize exige el claimId y persiste la decisión
        // ANTES de aplicarla al usuario; user=approved solo tras decisión
        // persistida; un fallo al aplicar es fail-closed (no hay rollback que
        // trague el error ni liberación que deje approved sin consumo).
        assert.match(postBody, /findOneAndUpdate\(/);
        assert.match(postBody, /decidedAt: null/);
        assert.match(postBody, /processingAt/);
        assert.match(postBody, /randomBytes/);
        const finalizeIdx = postBody.indexOf('$set: { decidedAt');
        assert.ok(finalizeIdx > -1, 'falta el finalize que persiste la decisión');
        assert.match(postBody.slice(Math.max(0, finalizeIdx - 400), finalizeIdx), /claimId/,
            'el finalize no exige el fence claimId');
        assert.match(postBody.slice(finalizeIdx), /\$unset: \{ processingAt/);
        assert.match(postBody.slice(finalizeIdx), /applyDecisionToUser\(/,
            'la decisión se persiste antes de tocar al usuario');
        assert.match(postBody, /matchedCount/);
        assert.doesNotMatch(postBody, /Nada quedó decidido/);
        assert.match(postBody, /410/);
    });
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
