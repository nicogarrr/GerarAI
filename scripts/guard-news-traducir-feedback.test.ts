// Guard: el botón «Traducir» del resumen de noticias nunca hace no-op
// silencioso — si el motor no devuelve traducción se muestra feedback.
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const SRC = readFileSync('components/research/NewsSummary.tsx', 'utf8');

test('estado de traducción no disponible declarado y visible con role=status', () => {
  assert.match(SRC, /const \[unavailable, setUnavailable\] = useState\(false\)/);
  assert.match(SRC, /role="status"/);
  assert.match(SRC, /Traducción no disponible ahora mismo/);
});

test('cualquier respuesta sin traducción activa el feedback (nunca no-op)', () => {
  assert.match(SRC, /else \{\s*setUnavailable\(true\);?\s*\}/);
  assert.match(SRC, /\.catch\(\(\) => setUnavailable\(true\)\)/);
});

test('el reintento limpia el feedback anterior', () => {
  assert.match(SRC, /setBusy\(true\);\s*setUnavailable\(false\);/);
});
