/**
 * Redaccion de credenciales en errores de frontera: mensaje, causa y log.
 *
 * fetch rechaza con la URL completa (?token=...) en el mensaje, y un DSN de
 * Redis/Postgres lleva la password en el userinfo. Sin redaccion en el
 * error de frontera Y en su causa, el secreto del servidor llegaba al log
 * del action y a una posible serializacion al navegador.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/secret-redaction.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { redactSecretsInText, redactUrl, sanitizeCause } from '../lib/upstream/redact.ts';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { ExternalAPIError } from '../lib/types/errors.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

const SECRET = 'VERYSECRET123';
const RAW_URL = `https://finnhub.io/api/v1/quote?symbol=AAPL&token=${SECRET}`;

describe('redactUrl', () => {
    it('redacta la credencial de la query', () => {
        const safe = redactUrl(RAW_URL);
        assert.ok(!safe.includes(SECRET), safe);
        assert.ok(safe.includes('token=REDACTED'), safe);
        assert.ok(safe.includes('symbol=AAPL'), safe);
    });

    it('redacta la password del userinfo', () => {
        const safe = redactUrl(`redis://worker:${SECRET}@cache:6379/0`);
        assert.ok(!safe.includes(SECRET), safe);
        assert.ok(safe.includes('REDACTED'), safe);
    });

    it('redacta con mayusculas y conserva duplicados', () => {
        // searchParams.has() distingue mayusculas y set() aplana repeticiones:
        // ?TOKEN= pasaba intacto y ?token=A&token=B dejaba B sin redactar.
        const upper = redactUrl(`https://x/?TOKEN=${SECRET}`);
        assert.ok(!upper.includes(SECRET), upper);
        assert.ok(upper.includes('TOKEN=REDACTED'), upper);
        const dup = redactUrl(`https://x/?token=${SECRET}&token=AGAINSECRET&symbol=AAPL`);
        assert.ok(!dup.includes(SECRET), dup);
        assert.ok(!dup.includes('AGAINSECRET'), dup);
        assert.equal(dup, 'https://x/?token=REDACTED&token=REDACTED&symbol=AAPL', dup);
        const mixed = redactUrl(`https://x/?ApiKey=${SECRET}&a=1`);
        assert.ok(!mixed.includes(SECRET), mixed);
    });

    it('una entrada que no es URL nunca vuelve intacta', () => {
        const safe = redactUrl(`no-es-url?token=${SECRET}`);
        assert.equal(safe, '[invalid URL]');
        assert.ok(!safe.includes(SECRET));
    });
});

describe('redactSecretsInText', () => {
    it('redacta userinfo y pares de query dentro de un traceback', () => {
        const raw = [
            `httpx.ConnectError: fallo al conectar con ${RAW_URL}`,
            `redis://worker:${SECRET}@cache:6379/0`,
            `postgresql://user:${SECRET}@db:5432/cavaai`,
        ].join('\n');
        const safe = redactSecretsInText(raw);
        assert.ok(!safe.includes(SECRET), safe);
        assert.ok(safe.includes('redis://worker:REDACTED@cache:6379/0'), safe);
        assert.ok(safe.includes('token=REDACTED'), safe);
    });
});

describe('sanitizeCause', () => {
    it('la causa conserva el tipo pero no la URL cruda', () => {
        const raw = new TypeError(`fetch failed: ${RAW_URL}`);
        const cause = sanitizeCause(raw) as Error;
        assert.ok(cause instanceof Error);
        assert.equal(cause.name, 'TypeError');
        assert.ok(!cause.message.includes(SECRET), cause.message);
        assert.ok(cause.message.includes('token=REDACTED'), cause.message);
    });

    it('una causa que no es Error ni string se descarta', () => {
        assert.equal(sanitizeCause({ url: RAW_URL }), undefined);
    });
});

describe('error de frontera: ni mensaje ni causa ni log llevan el secreto', () => {
    it('simulacion de fetch rechazando con URL+token', () => {
        // Lo que hace el catch de fetchJSON: fetch rechaza con la URL cruda,
        // el mensaje lleva redactUrl y la causa pasa por sanitizeCause.
        const fetchRejection = new TypeError(`fetch failed: ${RAW_URL}`);
        const boundary = new ExternalAPIError(
            `Unexpected error fetching ${redactUrl(RAW_URL)}`,
            'finnhub',
            sanitizeCause(fetchRejection),
        );
        assert.ok(!boundary.message.includes(SECRET), boundary.message);
        const cause = boundary.originalError as Error;
        assert.ok(cause instanceof Error, 'la causa sobrevive como Error');
        assert.ok(!cause.message.includes(SECRET), cause.message);

        // El action hace console.error(..., error): el volcado completo del
        // error de frontera (mensaje + causa + stack) no puede llevar la key.
        const captured: string[] = [];
        const original = console.error;
        console.error = (...args: unknown[]) => {
            captured.push(args.map((a) => (a instanceof Error ? `${a.message}${(a as { originalError?: unknown }).originalError ?? ''}` : String(a))).join(' '));
        };
        try {
            console.error('[getQuote] finnhub fallo', boundary);
        } finally {
            console.error = original;
        }
        assert.ok(captured.length > 0);
        assert.ok(!captured.join('\n').includes(SECRET), captured.join('\n'));
    });

    it('el catch de fetchJSON encadena sanitizeCause, no el error crudo (guarda de cableado)', () => {
        const src = readFileSync(join(root, 'lib/upstream/finnhub.ts'), 'utf8');
        const catchBlock = src.slice(src.lastIndexOf('} catch (error: unknown) {'));
        assert.ok(
            catchBlock.includes('sanitizeCause(error)'),
            'fetchJSON debe encadenar la causa sanitizada',
        );
        assert.ok(
            !/,\s*appError\s*\)/.test(catchBlock),
            'el error crudo (toAppError) no puede ser la causa del error de frontera',
        );
    });
});
