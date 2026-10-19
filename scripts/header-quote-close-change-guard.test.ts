import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const src = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');

test('closed-market variation is shown only from official-close fields, labelled and dated', () => {
  const block = src.slice(src.indexOf('data-testid="close-change"') - 400, src.indexOf('data-testid="close-change"') + 1600);
  assert.match(block, /quote\.session === 'cerrado'/);
  assert.match(block, /close_change_date && quote\.close_change_previous_date/);
  assert.match(src, /quote\?\.session === 'cerrado' && quote\.close_change_percent != null && quote\.close_change_date && quote\.close_change_previous_date \? <p[^>]*>Último cierre vs anterior/);
  assert.doesNotMatch(block, /previous_close\b/);
});
