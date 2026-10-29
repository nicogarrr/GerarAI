import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error node strip-types requires explicit extension.
import { thesisMoney, thesisEps } from '../lib/research/thesis-number-format.ts';
test('thesis USD keeps cents, non-USD keeps its own currency, missing EPS is not zero', () => {
 assert.equal(thesisMoney(343.46,'USD'),'343,46\u00a0US$');
 assert.equal(thesisMoney(250.75,'USD'),'250,75\u00a0US$');
 assert.match(thesisMoney(1477.2,'EUR'), /1\.477,20.*€/);
 assert.equal(thesisEps(4.71),'4,71');
 assert.equal(thesisEps(4.7),'4,70');
 assert.equal(thesisEps(null),'N/D');
});
