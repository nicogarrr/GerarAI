import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// El badge del chat por empresa no puede volver a decir "21 fuentes" mientras
// la lista muestra "Citas y evidencia (4)": mismo dato derivado con la misma
// función (toChatCitations) en badge y lista. Y pluraliza: "1 cita · 1 fuente".
test('badge y lista de citas usan la misma derivación y pluralizan', () => {
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  const list = readFileSync('components/chat/CitationsList.tsx', 'utf8');
  assert.ok(page.includes("import { toChatCitations } from '@/lib/chat/citations';"));
  assert.ok(page.includes("{toChatCitations(response.sources).length} {toChatCitations(response.sources).length === 1 ? 'cita' : 'citas'} · {response.sources.length} {response.sources.length === 1 ? 'fuente' : 'fuentes'}"));
  assert.ok(list.includes('toChatCitations(sources)'));
  assert.ok(!page.includes('>{response.sources.length} fuentes</Badge>'));
});

test('el markdown del chat de empresa no pinta imágenes remotas', () => {
  const component = readFileSync('components/research/ChatAnswerMarkdown.tsx', 'utf8');
  assert.ok(component.includes('disallowedElements'), 'falta disallowedElements');
  assert.ok(component.includes("'img'"), 'img debe estar bloqueado');
});
