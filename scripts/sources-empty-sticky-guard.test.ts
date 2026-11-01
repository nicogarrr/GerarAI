import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync(new URL('../app/(root)/research/sources/page.tsx', import.meta.url), 'utf8');

test('sources: el empty state de la tabla de documentos es visible a 390px', () => {
  // La tabla tiene min-w-[820px] dentro de OverflowScrollRegion: un mensaje
  // colSpan centrado cae fuera del viewport movil. En movil va a la izquierda
  // y acotado al viewport; el centrado solo aplica desde sm.
  const emptyRow = page.match(/\{!documents\.length \? \(([\s\S]*?)\) : null\}/);
  assert.ok(emptyRow, 'no se encontro la fila de empty state');
  assert.match(emptyRow[1], /text-left sm:mx-auto sm:w-fit sm:text-center/);
  assert.match(emptyRow[1], /max-w-\[calc\(100vw-6rem\)\]/);
});
