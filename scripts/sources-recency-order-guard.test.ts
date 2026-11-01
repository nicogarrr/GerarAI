/**
 * Guarda F162 (orden de «más recientes» en /research/sources): la etiqueta
 * dice «más recientes», así que el criterio es fecha de PUBLICACIÓN global -
 * no la ingesta (created_at), que agrupaba por tanda y escondía filings
 * recientes. Los sin fecha van al final y la tabla los etiqueta.
 * Ejecución: node --experimental-strip-types --test scripts/sources-recency-order-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));

void test('el backend ordena por publicación, sin fecha al final', () => {
    const src = readFileSync(join(here, '..', 'data-engine/app/api/routes/sources.py'), 'utf8');
    assert.ok(src.includes('desc(Document.published_at).nullslast()'), 'published_at DESC nulls last');
    assert.ok(src.includes('desc(Document.created_at)'), 'created_at solo desempata');
});

void test('la UI declara el criterio y etiqueta los sin fecha', () => {
    const src = readFileSync(join(here, '..', 'app/(root)/research/sources/page.tsx'), 'utf8');
    assert.ok(src.includes("t('research.sourcesPage.sortNote')") && JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).sourcesPage.sortNote.includes('por fecha de publicación'), 'criterio declarado junto a la cuenta');
    assert.ok(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).sourcesPage.sortNote.includes('sin fecha van al final'), 'sin fecha al final declarado');
    assert.ok(src.includes(": t('research.sourcesPage.noDate')") && JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).sourcesPage.noDate === 'sin fecha', 'celda «sin fecha» explícita, no un guion ambiguo');
});
