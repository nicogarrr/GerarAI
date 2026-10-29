import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error node strip-types needs extension.
import { formatProvenanceValue } from '../lib/research/provenance-format.ts';
test('terminal uses declared currency with English scale and no duplicate raw suffix',()=>{
 assert.equal(formatProvenanceValue(70918000,'USD'),'70,92 M\u00a0US$');
 assert.equal(formatProvenanceValue(19360000000,'USD'),'19,36 mil M\u00a0US$');
 assert.doesNotMatch(formatProvenanceValue(19360000000,'EUR'), /US\$/);
 const page=readFileSync('app/(root)/research/[ticker]/financial-terminal/page.tsx','utf8');
 assert.match(page,/formatProvenanceValue\(raw, unit\)/);
 assert.doesNotMatch(page,/>\{point.unit\}<\/span>/);
 assert.match(page,/N\/D \(unidad no disponible\)/);
});
