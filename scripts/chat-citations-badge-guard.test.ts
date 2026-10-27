import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// La lista de citas deriva con toChatCitations; la ficha ya no pinta chat propio.
test('la lista de citas deriva con toChatCitations y la ficha no pinta respuestas de chat', () => {
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  const list = readFileSync('components/chat/CitationsList.tsx', 'utf8');
  assert.ok(list.includes('toChatCitations(sources)'));
  assert.ok(!page.includes('response.sources'));
});
