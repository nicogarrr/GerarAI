import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { compactEnglish } from './i18n-compact-en.mjs';
// @ts-expect-error TS5097: node --experimental-strip-types needs the extension.
import { I18N_AREAS, getMessages } from '../lib/i18n/messages/index.ts';

test('compact English is current and smaller than duplicate key trees', () => {
  const compact = readFileSync('lib/i18n/messages/en.compact.json', 'utf8');
  assert.equal(compact, compactEnglish());
  const sourceBytes = I18N_AREAS.reduce((n, area) => n + Buffer.byteLength(JSON.stringify(
    JSON.parse(readFileSync(`lib/i18n/messages/en/${area}.json`, 'utf8')))), 0);
  assert.ok(Buffer.byteLength(compact) < sourceBytes * 0.85);
});

test('every English key and placeholder retains its exact source text', () => {
  for (const area of I18N_AREAS) {
    const expected = JSON.parse(readFileSync(`lib/i18n/messages/en/${area}.json`, 'utf8'));
    // JSON serialization removes missing leaves, as source dictionaries do.
    assert.deepEqual(JSON.parse(JSON.stringify(getMessages('en')[area])), expected, area);
  }
});
