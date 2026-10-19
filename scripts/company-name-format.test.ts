import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { formatCompanyName } from '../lib/format.ts';

test('formatCompanyName respeta marcas con &, guiones y sufijos /ADR', () => {
  assert.equal(formatCompanyName('AT&T INC'), 'AT&T Inc');
  assert.equal(formatCompanyName('COCA-COLA CO'), 'Coca-Cola Co');
  assert.equal(formatCompanyName('TOYOTA MOTOR CORP/ADR'), 'Toyota Motor Corp/ADR');
  assert.equal(formatCompanyName('Apple Inc'), 'Apple Inc');
  assert.equal(formatCompanyName('IBM'), 'IBM');
  assert.equal(formatCompanyName('COLLPLANT BIOTECHNOLOGIES LT'), 'Collplant Biotechnologies Ltd');
});
