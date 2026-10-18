import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
test('thesis long URLs wrap; markdown table/code retain bounded internal scroll', () => {
 for(const path of ['components/research/ThesisMemo.tsx','components/research/ThesisMarkdown.tsx']) {
  const src = readFileSync(path,'utf8');
  assert.match(src,/min-w-0 max-w-full/);
  assert.match(src,/\[overflow-wrap:anywhere\]/);
  assert.match(src,/text-teal-400 underline/);
 }
 const markdown = readFileSync('components/research/ThesisMarkdown.tsx','utf8');
 assert.match(markdown,/min-w-0 max-w-full overflow-x-auto/);
});
test('financial terminal scroll region is bounded and keyboard-accessible', () => {
 const src = readFileSync('app/(root)/research/[ticker]/financial-terminal/page.tsx','utf8');
 assert.match(src,/mt-4 w-full min-w-0 max-w-full overflow-x-auto overscroll-x-contain/);
 assert.match(src,/role="region" tabIndex=\{0\}/);
 assert.match(src,/min-w-\[640px\]/);
});
