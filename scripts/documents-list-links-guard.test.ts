/**
 * Guard F249 (lista de Documentos accionable): cada ficha enlaza a la
 * fuente primaria cuando el documento tiene source_url (los filings SEC
 * la traen); sin URL queda texto, nunca un enlace roto ni un div
 * estático con URL disponible. Enlaces externos con rel="noopener
 * noreferrer" y target="_blank".
 *
 * Ejecucion: node --experimental-strip-types --test scripts/documents-list-links-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

const list = readFileSync('components/research/DocumentsList.tsx', 'utf8');

describe('documents list links guard (F249)', () => {
  it('solo se enlaza una URL absoluta http(s)', () => {
    assert.match(page, /function safeHttpUrl/, 'helper de validación');
    assert.match(page, /new URL\(value\)/, 'parseo estricto');
    assert.match(page, /url\.protocol === 'https:' \|\| url\.protocol === 'http:'/, 'esquema http(s) únicamente');
    assert.match(page, /url\.hostname/, 'hostname obligatorio');
  });


  it('la ficha enlaza cuando hay source_url', () => {
    assert.match(page, /url: safeHttpUrl\(document\.source_url\)/, 'URL validada al construir las filas');
    assert.match(list, /d\.url \? <a[^>]*href=\{d\.url\}/, 'href solo desde fila validada');
    assert.equal(list.includes('href={document.source_url}'), false, 'source_url en crudo no puede ser href');
  });

  it('sin URL queda texto, no enlace roto', () => {
    assert.match(list, /: <span className="font-medium text-gray-200">\{d\.title\}<\/span>/, 'fallback a texto');
  });

  it('enlace externo seguro', () => {
    assert.match(list, /target="_blank"/);
    assert.match(list, /rel="noopener noreferrer"/);
  });
});
