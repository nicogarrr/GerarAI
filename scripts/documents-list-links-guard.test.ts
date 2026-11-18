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

const evidence = readFileSync('components/research/ClaimEvidenceList.tsx', 'utf8');

function assertSafeHttpUrlContract(source: string): void {
  assert.match(source, /export function safeHttpUrl/, 'helper de validación exportado');
  assert.match(source, /new URL\(value\)/, 'parseo estricto');
  assert.match(source, /url\.protocol === 'https:' \|\| url\.protocol === 'http:'/, 'esquema http(s) únicamente');
  assert.match(source, /url\.hostname/, 'hostname obligatorio');
}

const list = readFileSync('components/research/DocumentsList.tsx', 'utf8');

describe('documents list links guard (F249)', () => {
  it('solo se enlaza una URL absoluta http(s)', () => {
    assertSafeHttpUrlContract(evidence);
    assert.match(page, /import \{[^}]*\bsafeHttpUrl\b[^}]*\} from '@\/components\/research\/ClaimEvidenceList'/, 'la ficha importa el helper compartido');
  });


  it('el guard rechaza perder validación aunque el helper cambie de fichero', () => {
    for (const [pattern, replacement] of [
      [/export function safeHttpUrl/, 'export function unsafeUrl'],
      [/new URL\(value\)/, 'value'],
      [/url\.protocol === 'https:' \|\| url\.protocol === 'http:'/, 'true'],
      [/url\.hostname/g, 'true'],
    ] as const) {
      const mutated = evidence.replace(pattern, replacement);
      assert.notEqual(mutated, evidence, 'el control negativo debe alterar el contrato');
      assert.throws(() => assertSafeHttpUrlContract(mutated));
    }
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
