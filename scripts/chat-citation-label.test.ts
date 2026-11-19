/**
 * Las fuentes del chat no exponen IDs internos (thesis_version:1434...).
 * Ejecución: node --experimental-strip-types --test scripts/chat-citation-label.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { citationKindLabel } from '../lib/chat/citations.ts';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { createTranslator } from '../lib/i18n/translate.ts';

describe('citationKindLabel', () => {
  it('traduce los tipos internos a etiquetas legibles del idioma activo', () => {
    const t = createTranslator('es');
    assert.equal(citationKindLabel('thesis_version:1434', t), 'Tesis');
    assert.equal(citationKindLabel('financial_fact:99', t), 'Dato financiero');
    assert.equal(citationKindLabel('claim:7', t), 'Afirmación');
    assert.equal(citationKindLabel('rag_chunk:0f1e-uuid', t), 'Documento');
    assert.equal(citationKindLabel('desconocido:1', t), null);
    assert.equal(citationKindLabel('position:3', t), 'Posición');
  });
  it('en inglés pinta las etiquetas del Cerebro en inglés', () => {
    const t = createTranslator('en');
    assert.equal(citationKindLabel('thesis_section:4', t), 'Thesis section');
    assert.equal(citationKindLabel('memory_item:8', t), 'Saved note');
    assert.equal(citationKindLabel('knowledge_chunk:2', t), 'Library');
    assert.equal(citationKindLabel('desconocido:1', t), null);
  });
  it('ningún componente pinta el localizador crudo', () => {
    for (const file of ['components/brain/BrainSources.tsx']) {
      assert.ok(!/>\s*\{citation\.locator\}\s*</.test(readFileSync(file, 'utf8')), file);
    }
  });
});
