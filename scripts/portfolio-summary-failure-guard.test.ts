import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/portfolio/page.tsx', 'utf8');

test('a failed portfolio summary degrades to a retry notice instead of throwing (HTTP 500)', () => {
  const start = page.indexOf('if (!summaryResult.value)');
  const success = page.indexOf('} else {', start);
  assert.ok(start >= 0 && success > start, 'summary failure/success branches exist');
  const block = page.slice(start, success);
  assert.match(block, /isAuthError\(summaryResult\.cause\)/);
  assert.doesNotMatch(block, /throw /);
  // Sin resumen no se asignan summary ni tolerant; el aviso queda fuera del try.
  assert.doesNotMatch(block, /summary = summaryResult\.value|tolerant =/);
  const catchStart = page.indexOf('} catch (error) {', success);
  assert.ok(catchStart > success, 'outer data-loading catch exists');
  const afterCatch = page.slice(catchStart);
  assert.match(afterCatch, /if \(!summary \|\| !tolerant\) \{\s*return <BackendOffline/);
  const tryStart = page.indexOf('const summaryPromise');
  assert.ok(tryStart >= 0 && catchStart > tryStart, 'summary loading stays in try');
  const tryBlock = page.slice(tryStart, catchStart);
  assert.doesNotMatch(tryBlock, /<BackendOffline/);
});

test('the original error object is kept (code/statusCode are not rebuilt from the message)', () => {
  assert.match(page, /cause: error as unknown/);
});

test('/portfolio has a loading skeleton', () => {
  assert.ok(existsSync('app/(root)/portfolio/loading.tsx'));
});
