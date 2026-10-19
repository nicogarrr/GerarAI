import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// El badge del chat por empresa no puede volver a decir "21 fuentes" mientras
// la lista muestra "Citas y evidencia (4)": mismo dato derivado con la misma
// función (toChatCitations) en badge y lista.
test('badge y lista de citas usan la misma derivación', () => {
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  const list = readFileSync('components/chat/CitationsList.tsx', 'utf8');
  assert.ok(page.includes("import { toChatCitations } from '@/lib/chat/citations';"));
  assert.ok(page.includes('citas · {response.sources.length} fuentes'));
  assert.ok(list.includes('toChatCitations(sources)'));
  assert.ok(!page.includes('>{response.sources.length} fuentes</Badge>'));
});
