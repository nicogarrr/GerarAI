import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
test('header metrics fit two equal mobile columns without per-row left-padding mismatch', () => {
 const src=readFileSync('components/research/CompanyHeaderQuote.tsx','utf8');
 assert.ok(src.includes('grid min-w-0 grid-cols-2 gap-x-3'));
 assert.ok(src.includes('sm:grid-cols-4'));
 assert.ok(src.includes('min-w-0 py-3 sm:px-3 sm:first:pl-0'));
 assert.ok(!src.includes('px-2 py-3 first:pl-0'));
 assert.ok(src.includes('mt-1 break-words text-sm font-medium'));
});
