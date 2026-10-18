/**
 * La tabla de /knowledge pintaba las claves internas en inglés
 * («book» en Tipo, «native_text» en Extractor) y el visor de fragmentos
 * volcaba el markdown crudo (almohadillas de encabezado visibles).
 * Ahora: tipo y extractor con etiqueta en español (mismo vocabulario que
 * el select de subida) y fragmentos renderizados como markdown.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/knowledge-document-labels-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
const backend = readFileSync('data-engine/app/services/knowledge_library_service.py', 'utf8');

describe('knowledge document labels guard', () => {
  it('cada tipo del backend tiene etiqueta en español', () => {
    const typesBlock = backend.match(/KNOWLEDGE_DOCUMENT_TYPES = \{([^}]*)\}/);
    assert.ok(typesBlock, 'KNOWLEDGE_DOCUMENT_TYPES localizado');
    const backendTypes = [...typesBlock[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    assert.ok(backendTypes.length >= 9, 'el backend sigue declarando sus tipos');
    for (const t of backendTypes) {
      assert.match(page, new RegExp(`DOCUMENT_TYPE_LABELS[\\s\\S]*?\\n  ${t}: '`), `etiqueta para ${t}`);
    }
  });

  it('la tabla no pinta la clave cruda de tipo ni de extractor', () => {
    assert.ok(!page.includes('{document.document_type}</td>'), 'tipo crudo en tabla');
    assert.ok(!page.includes('{document.document_type}</Badge>'), 'tipo crudo en tarjeta');
    assert.ok(!page.includes("String(document.metadata.parser ?? 'desconocido')"), 'extractor crudo');
    for (const parser of ['native_text', 'native_html', 'pypdf', 'python_docx', 'openpyxl']) {
      assert.match(page, new RegExp(`PARSER_LABELS[\\s\\S]*?\\n  ${parser}: '`), `etiqueta para ${parser}`);
    }
  });

  it('los fragmentos se renderizan como markdown, no como texto crudo', () => {
    assert.match(page, /<ReactMarkdown remarkPlugins=\{\[remarkGfm\]} components=\{markdownComponents\}>\{chunk\.content\}<\/ReactMarkdown>/);
    assert.ok(!page.includes('<p className="whitespace-pre-wrap text-sm leading-6 text-gray-300">{chunk.content}</p>'), 'fragmento crudo');
  });
});
