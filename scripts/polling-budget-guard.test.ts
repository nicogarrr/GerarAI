import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
test('extraction backs off 30s to 60s and terminal props cancel timer', () => {
  const source = readFileSync('components/knowledge/ExtractionRefresh.tsx', 'utf8');
  assert.ok(source.includes('if (!active) return'));
  assert.ok(source.includes('30_000'));
  assert.ok(source.includes('Math.min(60_000, delay * 2)'));
  assert.ok(source.includes('window.clearTimeout(timer)'));
  assert.ok(source.includes("document.visibilityState === 'visible'"));
});
test('quotes cap visibility bursts and reduce periodic requests when closed', () => {
  const source = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');
  assert.ok(source.includes('Date.now() - lastRead < 300_000'));
  assert.ok(source.includes('activeSession || Date.now() - lastRead >= 1_800_000'));
  assert.ok(source.includes("value?.session === 'regular'"));
});
