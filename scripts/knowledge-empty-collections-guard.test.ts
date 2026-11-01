/**
 * La sección Colecciones de /knowledge pintaba las 10 colecciones por
 * defecto vacías con el mismo peso que las que tienen documentos (11
 * tarjetas, 10 de ruido, cada una con su botón Eliminar) antes de la tabla
 * de documentos. Ahora: las colecciones con documentos van primero y las
 * vacías quedan plegadas en un <details>, conservando su borrado.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/knowledge-empty-collections-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');

describe('knowledge empty collections guard', () => {
  it('separa colecciones con documentos de las vacías', () => {
    assert.match(page, /collectionsWithCount\.nonEmpty/);
    assert.match(page, /collectionsWithCount\.empty/);
  });

  it('las vacías quedan plegadas en un desplegable etiquetado', () => {
    assert.match(page, /<details className="mt-3">/);
    assert.match(page, /knowledge\.emptyCollections\.other/);
    assert.match(page, /knowledge\.emptyCollections\.one/);
    const esK = JSON.parse(readFileSync('lib/i18n/messages/es/knowledge.json', 'utf8'));
    assert.match(esK.emptyCollections.other, /colecciones vacías/);
    assert.match(esK.emptyCollections.one, /colección vacía/);
  });

  it('las vacías conservan su botón de borrado dentro del desplegable', () => {
    const details = page.match(/<details className="mt-3">[\s\S]*?<\/details>/);
    assert.ok(details, 'desplegable localizado');
    assert.match(details[0], /<DeleteCollectionButton collectionId=\{collection\.id\} name=\{collection\.name\} \/>/);
  });

  it('la lista principal ya no repite "en esta vista" ni muestra vacías', () => {
    assert.ok(!page.includes('documentos en esta vista'), 'copy "en esta vista" eliminado');
  });
});

describe('knowledge stale document param guard', () => {
  it('los fragmentos solo se piden si el documento existe en la biblioteca', () => {
    const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
    assert.match(page, /await getKnowledgeDocument\(selectedDocumentId\)/);
    assert.match(page, /if \(selectedExists\) \{[\s\S]*?getKnowledgeDocumentChunks\(selectedDocument!\.id\)/);
    assert.ok(!page.includes('Promise.all([getKnowledgeLibrary(), getKnowledgeDocumentChunks(selectedDocumentId)])'), 'ya no se piden fragmentos a ciegas en paralelo');
  });
});
