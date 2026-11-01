import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error explicit extension for node
import { extractionResultText, noPrinciplesText } from '../lib/knowledge/job-feedback.ts';
// @ts-expect-error explicit extension for node
import { createTranslator } from '../lib/i18n/translate.ts';

const en = createTranslator('en');
const job = (status: string, result: Record<string, unknown> = {}, error: string | null = null) => ({ status, result, error });

test('job feedback on /knowledge follows the chosen language (English)', () => {
  assert.equal(extractionResultText(job('completed', { principle_ids: [1, 2] }), en), 'Extraction completed: 2 principles found.');
  assert.equal(extractionResultText(job('partial', { principle_ids: [7] }), en), 'Partial extraction: 1 principle found.');
  assert.equal(extractionResultText(job('completed'), en), 'Extraction completed: Count not available.');
  assert.equal(extractionResultText(job('failed', {}, 'timeout after 1 attempt'), en), 'The extraction took too long. Try again.');
  assert.equal(extractionResultText(job('failed', {}, 'RateLimit 429'), en), 'The extraction service is not available right now. Try again later.');
  assert.equal(noPrinciplesText([], en), 'No principles extracted yet.');
  assert.equal(noPrinciplesText([job('partial', { principle_ids: [] })], en), 'The last extraction stopped halfway and left no principles.');
  assert.equal(noPrinciplesText([job('completed', { principle_ids: [] })], en), 'The last extraction finished without finding any principles.');
});

test('Spanish stays the default and unchanged', () => {
  assert.equal(extractionResultText(job('completed', { principle_ids: [1, 2] })), 'Extracción completada: 2 principios encontrados.');
  assert.equal(extractionResultText(job('partial')), 'Extracción parcial: Recuento no disponible.');
  assert.equal(noPrinciplesText([]), 'Aún no hay principios extraídos.');
});

test('the page passes its translator to the job feedback', () => {
  const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
  assert.ok(page.includes('extractionResultText(job, t)'));
  assert.ok(page.includes('noPrinciplesText(jobs, t)'));
});
