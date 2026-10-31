/**
 * Las fuentes del chat no exponen IDs internos (thesis_version:1434...).
 * Ejecución: node --experimental-strip-types --test scripts/chat-citation-label.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { citationKindLabel } from '../lib/chat/citations.ts';

describe('citationKindLabel', () => {
  it('traduce los tipos internos a etiquetas legibles', () => {
    assert.equal(citationKindLabel('thesis_version:1434'), 'Tesis');
    assert.equal(citationKindLabel('financial_fact:99'), 'Dato financiero');
    assert.equal(citationKindLabel('claim:7'), 'Afirmación');
    assert.equal(citationKindLabel('rag_chunk:0f1e-uuid'), 'Documento');
    assert.equal(citationKindLabel('desconocido:1'), null);
    assert.equal(citationKindLabel('position:3'), 'Posición');
  });
  it('ningún componente pinta el localizador crudo', () => {
    for (const file of ['components/brain/BrainSources.tsx']) {
      assert.ok(!/>\s*\{citation\.locator\}\s*</.test(readFileSync(file, 'utf8')), file);
    }
  });
});
