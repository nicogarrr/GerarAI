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
 // El terminal es una sección de la pestaña Finanzas desde el 29-oct-2026.
 const src = readFileSync('components/research/sections/FinancialTerminalSection.tsx','utf8');
 assert.match(src,/OverflowScrollRegion/);
 assert.match(src,/className="mt-4 w-full min-w-0 max-w-full"/);
 assert.match(src,/regionClassName="overscroll-x-contain"/);
 assert.match(src,/min-w-\[640px\]/);
 const region = readFileSync('components/ui/overflow-scroll-region.tsx','utf8');
 assert.match(region,/overflow-x-auto/);
 assert.match(region,/role="region"/);
 assert.match(region,/tabIndex=\{0\}/);
});
