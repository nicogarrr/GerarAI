import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error TS5097: node requires an explicit extension.
import { ownershipManagerName } from '../lib/ownership-display.ts';
test('display names use reviewed CIKs and preserve unknown official names', () => {
 assert.equal(ownershipManagerName('0001061768', 'BAUPOST GROUP LLC/MA'), 'Baupost Group');
 assert.equal(ownershipManagerName('0001376879', 'AKO CAPITAL LLP'), 'AKO Capital');
 assert.equal(ownershipManagerName('unknown', 'ABC LLC'), 'ABC LLC');
});
