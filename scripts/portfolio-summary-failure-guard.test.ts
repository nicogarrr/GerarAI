import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/portfolio/page.tsx', 'utf8');

test('a failed portfolio summary degrades to a retry notice instead of throwing (HTTP 500)', () => {
  const block = page.slice(page.indexOf('if (!summaryResult.value)'), page.indexOf('result = ['));
  assert.match(block, /isAuthError\(summaryResult\.cause\)/);
  assert.doesNotMatch(block, /throw /);
  // Sin resumen no se asigna result; el aviso se pinta FUERA del try/catch
  // (react-hooks/error-boundaries: nada de JSX dentro de try).
  const afterCatch = page.slice(page.indexOf('} catch (error) {'));
  assert.match(afterCatch, /if \(!result\) \{\s*return <BackendOffline/);
  const tryBlock = page.slice(page.indexOf('const [summaryResult'), page.indexOf('} catch (error) {'));
  assert.doesNotMatch(tryBlock, /<BackendOffline/);
});

test('the original error object is kept (code/statusCode are not rebuilt from the message)', () => {
  assert.match(page, /cause: error as unknown/);
});

test('/portfolio has a loading skeleton', () => {
  assert.ok(existsSync('app/(root)/portfolio/loading.tsx'));
});
