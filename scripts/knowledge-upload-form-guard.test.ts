/**
 * Guard F142 (formulario de subida de conocimiento localizado y guiado):
 * /knowledge?tab=subir mezclaba campos sin etiqueta visible con valores de
 * ejemplo en inglés («book», «en», «Choose File» del navegador en-US) y un
 * textbox libre de tipo que no declaraba el vocabulario aceptado. Ahora:
 * etiquetas visibles en español, selects con el vocabulario real del
 * backend (KNOWLEDGE_DOCUMENT_TYPES, language es|en) y disparador de
 * archivo en español.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/knowledge-upload-form-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
const upload = readFileSync('components/forms/FileUploadInput.tsx', 'utf8');
const backend = readFileSync('data-engine/app/services/knowledge_library_service.py', 'utf8');
const backendRoutes = readFileSync('data-engine/app/api/routes/knowledge.py', 'utf8');

describe('knowledge upload form guard (F142)', () => {
  it('cada campo tiene etiqueta visible asociada', () => {
    for (const [id, label] of [
      ['kw-title', 'Título'],
      ['kw-collection', 'Colección'],
      ['kw-author', 'Autor'],
      ['kw-doctype', 'Tipo de documento'],
      ['kw-pubdate', 'Fecha de publicación'],
      ['kw-language', 'Idioma del documento'],
    ]) {
      assert.match(page, new RegExp(`htmlFor="${id}"[^>]*>${label}`), `etiqueta ${label}`);
    }
  });

  it('el tipo es un select con el vocabulario exacto del backend', () => {
    const typesBlock = backend.match(/KNOWLEDGE_DOCUMENT_TYPES = \{([^}]*)\}/);
    assert.ok(typesBlock, 'KNOWLEDGE_DOCUMENT_TYPES localizado');
    const backendTypes = [...typesBlock[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
    assert.deepEqual(backendTypes, ['article', 'book', 'fund_letter', 'historical_case', 'own_thesis', 'paper', 'personal_note', 'personal_postmortem', 'sector_report', 'third_party_thesis']);
    for (const t of backendTypes) {
      assert.ok(page.includes(`value="${t}"`), `option ${t} presente`);
    }
    assert.equal(page.includes('name="document_type" defaultValue="book" placeholder'), false, 'sin textbox libre de tipo');
  });

  it('el idioma es un select es|en (el backend rechaza otros)', () => {
    assert.match(page, /name="language" defaultValue="en" required/, 'select de idioma');
    assert.ok(page.includes('<option value="es">Español</option>'), 'opción Español');
    assert.ok(page.includes('<option value="en">Inglés</option>'), 'opción Inglés');
    assert.match(backendRoutes, /normalized_language not in \("en", "es"\)/, 'el backend sigue validando es|en');
  });

  it('el selector de archivo habla español, no el idioma del navegador', () => {
    const esErrors = JSON.parse(readFileSync('lib/i18n/messages/es/errors.json', 'utf8'));
    assert.equal(esErrors.upload.choose, 'Elegir archivo', 'disparador en español');
    assert.ok(upload.includes("t('errors.upload.choose')"), 'el disparador consume la clave i18n');
    assert.equal(esErrors.upload.noFile, 'Ningún archivo seleccionado', 'estado vacío en español');
    assert.ok(upload.includes("t('errors.upload.noFile')"), 'el estado vacío consume la clave i18n');
    assert.match(upload, /className="sr-only"/, 'input nativo oculto pero accesible');
  });
});
