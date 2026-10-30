/**
 * Comportamiento: la vista activa de /research/[ticker] degrada a BackendOffline
 * solo con caida reconocida del motor; 4xx/auth/programacion se relanzan.
 * Ejecucion: node --experimental-strip-types --test scripts/research-ticker-view-offline-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const errorsUrl = pathToFileURL(join(root, 'lib/types/errors.ts')).href;
const dir = mkdtempSync(join(tmpdir(), 'vo-'));
const boFile = join(dir, 'backend-offline.ts');
writeFileSync(boFile, readFileSync(join(root, 'lib/backend-offline.ts'), 'utf8').replace("'@/lib/types/errors'", `'${errorsUrl}'`));

const { isBackendUnavailableError } = await import(pathToFileURL(boFile).href);
// view-outage importa research-views por alias: se reescribe a URL de archivo
// para poder ejecutarlo con node --experimental-strip-types.
const viewsUrl = pathToFileURL(join(root, 'lib/research/research-views.ts')).href;
const voFile = join(dir, 'view-outage.ts');
writeFileSync(voFile, readFileSync(join(root, 'lib/research/view-outage.ts'), 'utf8').replace("'@/lib/research/research-views'", `'${viewsUrl}'`));
const { findUnavailableViewFailure, viewRetryHref } = await import(pathToFileURL(voFile).href);
const { AppError, ExternalAPIError } = await import(errorsUrl);

const fail = (error: unknown) => [{ key: 'thesis', ok: false as const, reason: 'x', error }];

test('red/timeout y 5xx degradan', () => {
    assert.deepEqual(findUnavailableViewFailure(fail(new ExternalAPIError('t', 'research-engine')), isBackendUnavailableError), { key: 'thesis', reason: 'x' });
    assert.ok(findUnavailableViewFailure(fail(new AppError('x', 'RESEARCH_API_ERROR', 503)), isBackendUnavailableError));
});

test('4xx, auth, TypeError y errores sin clase NO degradan (se relanzan en viewData)', () => {
    for (const e of [new AppError('x', 'RESEARCH_API_ERROR', 401), new AppError('x', 'RESEARCH_API_ERROR', 422), new TypeError('bug'), undefined, 'texto']) {
        assert.equal(findUnavailableViewFailure(fail(e), isBackendUnavailableError), null);
    }
});

test('lecturas correctas o lista vacia no degradan', () => {
    assert.equal(findUnavailableViewFailure([], isBackendUnavailableError), null);
    assert.equal(findUnavailableViewFailure([{ key: 'k', ok: true, value: 1 }], isBackendUnavailableError), null);
});

test('retryHref conserva la vista y codifica el ticker', () => {
    assert.equal(viewRetryHref('ASTS', 'overview'), '/research/ASTS');
    assert.equal(viewRetryHref('ASTS', 'thesis'), '/research/ASTS?view=tesis');
    assert.equal(viewRetryHref('BRK.B', 'financials'), '/research/BRK.B?view=finanzas');
    assert.equal(viewRetryHref('A B', 'model'), '/research/A%20B?view=valoracion#modelo');
});

test('la pagina usa el helper antes de viewData y viewData sigue relanzando', () => {
    const src = readFileSync(join(root, 'app/(root)/research/[ticker]/page.tsx'), 'utf8');
    // Solo la lectura de la sección de ENTRADA degrada la página entera;
    // el resto de secciones muestran su aviso inline (29-oct-2026).
    assert.match(src, /findUnavailableViewFailure\(entrySettled, isBackendUnavailableError\)/);
    assert.ok(src.indexOf('findUnavailableViewFailure(viewSettled') < src.indexOf('const viewData = async'));
    assert.match(src.slice(src.indexOf('const viewData = async')), /throw failed\.error instanceof Error/);
});
