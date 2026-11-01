/**
 * Guarda de honestidad del inventario de Fuentes (F131): /api/sources/documents
 * pagina (50 por defecto), asi que la cabecera no puede presentar
 * documents.length como si fuera el total - el total real viene de
 * /documents/count y la tabla declara cuando esta truncada.
 * Ejecución: node --experimental-strip-types --test scripts/sources-count-honesty-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const ES_SOURCES = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).sourcesPage;
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

void test('la cabecera usa el total real de /documents/count, no el tamano de pagina', () => {
    const page = source('app/(root)/research/sources/page.tsx');
    assert.ok(page.includes('documentsTotal'), 'la pagina recibe el total real');
    // documents.length solo es legitimo en la nota de truncado; en la cabecera
    // el conteo de documentos debe salir de documentsTotal.
    // Vetado el chip antiguo (tamano de pagina presentado como total); la
    // variante con alcance declarado («en esta página») es legitima (F154).
    assert.ok(
        !page.includes("{formatNumber(documents.length, { maximumFractionDigits: 0 })} documentos ·{' '}"),
        'la cabecera no puede contar con el tamano de pagina',
    );
    const actions = source('lib/actions/research.actions.ts');
    assert.ok(actions.includes('`/api/sources/documents/count${countQuery}`'), 'la accion pide el total al backend (con el mismo filtro que el listado, F131)');
});

void test('si /count no responde el total es desconocido, nunca un 0 fingido (F154)', () => {
    const actions = source('lib/actions/research.actions.ts');
    assert.ok(
        !actions.includes("getJson<{ total: number }>('/api/sources/documents/count', { total: 0 })"),
        'fallback { total: 0 } pinta «0 documentos» con la tabla poblada (backend antiguo sin /count)',
    );
    assert.ok(
        actions.includes('getJson<{ total: number } | null>(`/api/sources/documents/count${countQuery}`, null)'),
        'el fallback honesto es null (total desconocido)',
    );
    const page = source('app/(root)/research/sources/page.tsx');
    assert.ok(
        page.includes('documentsTotal !== null'),
        'la cabecera y el truncado solo usan el total cuando es conocido',
    );
    assert.ok(
        page.includes("t('research.sourcesPage.docsOnPage'") && ES_SOURCES.docsOnPage.includes('documentos en esta página'),
        'con total desconocido se declara el alcance: documentos de esta página',
    );
});

void test('la tabla declara cuando esta truncada', () => {
    const page = source('app/(root)/research/sources/page.tsx');
    assert.ok(page.includes('(pageInfo?.pages ?? 1) > 1'), 'condicion de paginacion presente');
    assert.ok(page.includes("t('research.sourcesPage.showing") && ES_SOURCES.showing.startsWith('Mostrando {from}-{to} de {total}'), 'el rango visible se declara (X-Y de N), no solo el total');
    assert.ok(ES_SOURCES.sortNote === 'por fecha de publicación; los documentos sin fecha van al final.' && page.includes("t('research.sourcesPage.sortNote')"), 'copy honesto del orden');
});

void test('/documents/count se registra antes que /documents/{document_id} (FastAPI casa en orden)', () => {
    const backend = source('data-engine/app/api/routes/sources.py');
    const countAt = backend.indexOf('"/documents/count"');
    const byIdAt = backend.indexOf('"/documents/{document_id}/chunks"');
    assert.ok(countAt > -1 && byIdAt > -1, 'ambas rutas existen');
    assert.ok(countAt < byIdAt, 'count primero: si no, FastAPI intentaria parsear "count" como document_id');
});
