import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { isTranslatable } from '../lib/news-language.ts';

// Tester 4 nº6 (19-oct-2026): filas Yahoo con y sin botón «Traducir» por huecos
// de la heurística. Regla espejo de needs_translation del motor; los valores
// esperados están verificados contra Python (test_needs_translation_language_marks).
// Decisión del auditor: sin marcas claras NO es traducible, salvo Title Case
// de >=3 palabras. Los \b son lookarounds Unicode (flag u) para paridad con
// Python en textos acentuados.

test('español claro no es traducible', () => {
  assert.equal(isTranslatable('La empresa anuncia resultados'), false);
  assert.equal(isTranslatable('CPT eleva el dividendo tras superar las expectativas de ingresos'), false);
});

test('titulares españoles sin marcas de lista tampoco (objeción del auditor)', () => {
  assert.equal(isTranslatable('Inditex bate previsiones'), false);
  assert.equal(isTranslatable('Iberdrola eleva beneficio'), false);
  assert.equal(isTranslatable('BBVA gana 5.000 millones'), false);
});

test('acentos: paridad con Python (el \b ASCII de JS casaba marcas inglesas dentro de palabras acentuadas)', () => {
  assert.equal(isTranslatable('Las compañías del Ibex suben'), false);
  assert.equal(isTranslatable('Energías renovables lideran el Ibex'), false);
  assert.equal(isTranslatable('Las economías emergentes crecen'), false);
  assert.equal(isTranslatable('Ñandú Capital invierte'), false);
});

test('inglés, Title Case anglosajón (también acentuado) y no latino son traducibles', () => {
  assert.equal(isTranslatable('Apple reports earnings after the bell'), true);
  assert.equal(isTranslatable('Meta Llama Beats Rivals Again'), true);
  assert.equal(isTranslatable('Müller Sachs Group Holdings'), true);
  assert.equal(isTranslatable('Εταιρεία ανακοινώνει αποτελέσματα'), true);
});

test('los componentes usan el helper compartido', () => {
  const summary = readFileSync('components/research/NewsSummary.tsx', 'utf8');
  const headline = readFileSync('components/research/NewsHeadline.tsx', 'utf8');
  for (const src of [summary, headline]) {
    assert.ok(src.includes("from '@/lib/news-language'"), 'usa lib/news-language');
    assert.ok(!src.includes('nonLatin') && !src.includes('ENGLISH_MARK'), 'sin regexes propias');
  }
});
