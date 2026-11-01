// Guard: el feed de Noticias destacadas es una lista de filas estilo feed
// (pedido de Nico 1-nov-2026, referencia Quartr): logo de empresa + nombre +
// titular + antigüedad compacta. Sin imágenes grandes, sin etiqueta de fuente
// pintada y sin duplicados.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/NewsSection.tsx', 'utf8');

test('filas de feed: logo, edad compacta, dedupe y sin imagen ni fuente pintada', () => {
    assert.ok(SRC.includes('dedupeArticles(news)'), 'la lista se deduplica (titular normalizado o URL)');
    assert.ok(SRC.includes('formatAgeShort'), 'antigüedad compacta («22 h», «1 d»)');
    assert.ok(SRC.includes('CompanyLogo'), 'logo de empresa en cada fila con ticker');
    assert.ok(!SRC.includes('next/image'), 'sin imágenes grandes de proveedor');
    assert.ok(!SRC.includes('{article.source}'), 'la fuente ya no se pinta en la UI');
});
