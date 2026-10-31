import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const source = readFileSync('app/(root)/portfolio/page.tsx', 'utf8');
test('portfolio partial banner uses safe error categories, never raw backend messages', () => {
    assert.match(source, /secondaryErrors\.map\(\(error\) => t\(sectionErrorKey\(new Error\(error\)\)\)\)/);
    assert.doesNotMatch(source, /\$\{secondaryErrors\.join\(/);
    assert.match(source, /new Set\(secondaryErrors\.map/);
});
