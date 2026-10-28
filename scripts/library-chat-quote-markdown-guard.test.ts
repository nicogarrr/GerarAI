import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// Guard de render: las citas de Preguntar a la biblioteca salen de cartas que
// pueden contener markdown (tablas, listas). Renderizarlas como texto plano
// mostraba tuberías crudas ("| dividendo | estable |"). Deben pasar por
// ReactMarkdown, igual que los fragmentos de /knowledge.
const src = readFileSync('components/brain/BrainLibraryAnswer.tsx', 'utf8');

test('las citas del chat de biblioteca se renderizan como markdown, no como texto crudo', () => {
  const quotes = src.match(/blockquote[\s\S]*?citation\.quote[\s\S]*?blockquote/g) ?? [];
  assert.equal(quotes.length, 2, 'hay dos blockquotes de cita (respuesta y punto de análisis)');
  for (const block of quotes) {
    const md = block.indexOf('<ReactMarkdown');
    const quote = block.indexOf('citation.quote');
    assert.ok(md !== -1 && md < quote, `la cita va dentro de ReactMarkdown, no como texto crudo: ${block.slice(0, 120)}`);
    assert.ok(block.indexOf('</ReactMarkdown>') > quote, 'ReactMarkdown cierra después de la cita');
  }
});
