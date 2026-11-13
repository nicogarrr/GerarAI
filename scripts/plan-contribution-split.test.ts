/**
 * Reparto de la aportación por nivel DCA: textos y estados de la tarjeta del plan.
 *   node --experimental-strip-types --test scripts/plan-contribution-split.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { isContributionSplit, levelTone } from '../lib/plan/contribution-split.ts';

describe('reparto de la aportación por nivel DCA', () => {
  it('valida la forma y colorea el nivel', () => {
    assert.equal(isContributionSplit({ plan_exists: true }), true);
    assert.equal(isContributionSplit({ detail: 'Not Found' }), false);
    assert.equal(levelTone(null), 'text-gray-500');
    assert.equal(levelTone(-1), 'text-amber-300');
    assert.equal(levelTone(4), 'text-teal-300');
  });
});
