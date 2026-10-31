/**
 * Biblioteca ↔ ticker (conexión 10a): un documento de la biblioteca puede
 * llevar el ticker de la empresa a la que se refiere y aparece en la ficha
 * /research/[ticker] (vista Documentos → «Lecturas de la biblioteca»).
 *
 * Funciones reales (no regex sobre el código) + dos guards de cableado.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/knowledge-document-ticker.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { knowledgeTickerFormValue, libraryDocumentHref, libraryReadingsPath } from '../lib/knowledge/document-ticker.ts';

describe('knowledgeTickerFormValue', () => {
  it('normaliza a mayúsculas sin espacios', () => {
    assert.equal(knowledgeTickerFormValue(' san.mc '), 'SAN.MC');
    assert.equal(knowledgeTickerFormValue('brk-b'), 'BRK-B');
  });
  it('vacío o ausente es null (quita el ticker)', () => {
    assert.equal(knowledgeTickerFormValue(''), null);
    assert.equal(knowledgeTickerFormValue('   '), null);
    assert.equal(knowledgeTickerFormValue(null), null);
  });
  it('un File no es un ticker', () => {
    assert.equal(knowledgeTickerFormValue(new File(['x'], 'x.txt')), null);
  });
});

describe('rutas de la biblioteca por ticker', () => {
  it('pide solo documentos listos del ticker, codificado', () => {
    assert.equal(
      libraryReadingsPath('SAN.MC'),
      '/api/knowledge/documents?ticker=SAN.MC&status=ready&limit=50',
    );
    assert.equal(
      libraryReadingsPath('^GSPC'),
      '/api/knowledge/documents?ticker=%5EGSPC&status=ready&limit=50',
    );
  });
  it('enlaza al explorador de fragmentos del documento', () => {
    assert.equal(libraryDocumentHref(42), '/knowledge?document=42');
  });
});

describe('cableado en las páginas', () => {
  const research = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  const knowledge = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
  const actions = readFileSync('lib/actions/research-tools.actions.ts', 'utf8');

  it('la vista Documentos de la ficha lista las lecturas de la biblioteca', () => {
    assert.match(research, /research\.fichaLibraryReadings/);
    assert.match(research, /getKnowledgeDocumentsForTicker\(ticker\)/);
  });

  it('la subida acepta ticker y el explorador permite asignarlo', () => {
    assert.match(knowledge, /name="ticker"/);
    assert.match(knowledge, /setKnowledgeDocumentTicker\.bind\(null, selectedDocument\.id\)/);
    assert.match(actions, /method: 'PATCH'/);
  });
});
