/**
 * Guarda: /research/news y /research/sources degradan a BackendOffline solo
 * cuando el backend esta caido (red o 5xx) y propagan el resto de errores.
 * Antes, un fallo breve de la API llegaba al error boundary generico.
 * Ejecucion: node --experimental-strip-types --test scripts/research-pages-backend-offline-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');
const pages = ['app/(root)/research/news/page.tsx', 'app/(root)/research/sources/page.tsx'];

for (const page of pages) {
    test(`${page}: degrada solo con backend caido y propaga lo demas`, () => {
        const src = read(page);
        assert.match(src, /import \{ isBackendUnavailableError \} from '@\/lib\/backend-offline'/);
        assert.match(src, /import BackendOffline from '@\/components\/system\/BackendOffline'/);
        const catchBlock = src.slice(src.indexOf('} catch (error) {'));
        assert.match(catchBlock, /if \(isBackendUnavailableError\(error\)\)/);
        assert.match(catchBlock, /<BackendOffline/);
        // La captura no puede tragarse el resto: debe haber rethrow tras el if.
        assert.match(catchBlock, /throw error;/);
        assert.ok(catchBlock.indexOf('throw error;') > catchBlock.indexOf('<BackendOffline'));
        // retryHref conserva la ruta y no deja un '?' vacio.
        assert.match(src, /retryQuery \? `\/research\/(news|sources)\?\$\{retryQuery\}` : '\/research\/(news|sources)'/);
    });
}

test('news: la promesa de contexto no queda sin consumir en la salida temprana', () => {
    assert.match(read(pages[0]), /tickerContextPromise\.catch\(\(\) => undefined\)/);
});

test('clasificacion: 4xx no cuentan como backend caido', () => {
    const lib = read('lib/backend-offline.ts');
    assert.match(lib, /error\.code === 'EXTERNAL_API_ERROR'/);
    assert.match(lib, /RESEARCH_API_ERROR' && error\.statusCode >= 500/);
    assert.doesNotMatch(lib, /statusCode >= 400/);
});

test('clasificacion real: red/5xx sí, 4xx/auth/programación no', async () => {
    const { mkdtempSync, writeFileSync } = await import('node:fs');
    const { tmpdir } = await import('node:os');
    const { pathToFileURL } = await import('node:url');
    const errorsUrl = pathToFileURL(join(here, '..', 'lib/types/errors.ts')).href;
    const dir = mkdtempSync(join(tmpdir(), 'bo-'));
    const file = join(dir, 'backend-offline.ts');
    writeFileSync(file, read('lib/backend-offline.ts').replace("'@/lib/types/errors'", `'${errorsUrl}'`));
    const { isBackendUnavailableError } = await import(pathToFileURL(file).href);
    const { AppError, ExternalAPIError } = await import(errorsUrl);
    assert.equal(isBackendUnavailableError(new ExternalAPIError('x', 'research-api')), true);
    assert.equal(isBackendUnavailableError(new AppError('x', 'RESEARCH_API_ERROR', 503)), true);
    assert.equal(isBackendUnavailableError(new AppError('x', 'RESEARCH_API_ERROR', 401)), false);
    assert.equal(isBackendUnavailableError(new AppError('x', 'RESEARCH_API_ERROR', 422)), false);
    assert.equal(isBackendUnavailableError(new TypeError('bug')), false);
});
