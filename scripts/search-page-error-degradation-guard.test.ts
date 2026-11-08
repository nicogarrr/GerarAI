/**
 * Guarda: /search degrada CUALQUIER fallo de la búsqueda al estado local
 * BackendOffline (página utilizable con Reintentar), nunca al ErrorBoundary
 * global (crash «Se produjo un error inesperado», hallazgo 2026-11-08:
 * cualquier consulta reventaba la página entera en prod). A diferencia de
 * /research/news|sources, que propagan 4xx/programación, aquí la búsqueda es
 * una sola consulta recuperable reintentando: el detalle queda en logs.
 * Ejecución: node --experimental-strip-types --test scripts/search-page-error-degradation-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'app/(root)/search/page.tsx'), 'utf8');

void test('/search: ningún fallo de búsqueda llega al ErrorBoundary', () => {
    const catchBlock = src.slice(src.indexOf('} catch (error) {'));
    assert.match(catchBlock, /<BackendOffline/);
    assert.doesNotMatch(catchBlock, /throw error;/, 'el catch no puede re-lanzar: eso era el crash de página');
    // El detalle del error inesperado se conserva en logs, no se oculta.
    assert.match(catchBlock, /console\.error/);
});

void test('/search: el estado local conserva la consulta en el Reintentar', () => {
    assert.match(src, /retryHref=\{currentHref\}/);
});

void test('/search: un fallo al PINTAR resultados queda contenido en la sección', () => {
    // El 200 con forma hostil revienta en render (results.map), fuera del
    // try/catch: una barrera con el mismo estado local acota el daño.
    assert.match(src, /import \{ ErrorBoundary \} from '@\/components\/ErrorBoundary'/);
    assert.match(src, /<ErrorBoundary fallback=\{<BackendOffline/);
    assert.match(src, /<BackendOffline as="section"/, 'el fallback de sección no puede anidar otro <main>');
});

void test('el adaptador del buscador vive en un módulo puro testeable', () => {
    const actions = readFileSync(join(here, '..', 'lib/actions/research-tools.actions.ts'), 'utf8');
    assert.match(actions, /from '@\/lib\/research\/universal-search'/);
    const adapter = readFileSync(join(here, '..', 'lib/research/universal-search.ts'), 'utf8');
    assert.match(adapter, /Array\.isArray/, 'results/items deben coercionar a array');
});
