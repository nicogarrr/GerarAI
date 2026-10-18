import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error Explicit extension for strip-types.
import { hasPriorClose } from '../lib/market/session-change.ts';
test('placeholder zero change needs a positive prior close; real flat session stays zero', () => {
 for (const quote of [null, {}, { pc: null }, { pc: 0 }, { pc: NaN }, { pc: -1 }]) assert.equal(hasPriorClose(quote), false);
 assert.equal(hasPriorClose({ pc: 100 }), true);
});
