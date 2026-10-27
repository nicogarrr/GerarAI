/**
 * Reparto de la aportación por nivel DCA: textos y estados de la tarjeta del plan.
 *   node --experimental-strip-types --test scripts/plan-contribution-split.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { formatSplitAmount, isContributionSplit, levelTone, splitEmptyMessage } from '../lib/plan/contribution-split.ts';

describe('reparto de la aportación por nivel DCA', () => {
  it('formatea importes en es-ES con la divisa del plan', () => {
    assert.equal(formatSplitAmount(225, 'EUR'), '225,00 EUR');
    assert.equal(formatSplitAmount(1234.5, 'EUR'), '1.234,50 EUR');
    assert.equal(formatSplitAmount(75, null), '75,00');
  });

  it('estados vacíos honestos', () => {
    assert.match(splitEmptyMessage(null) ?? '', /Configura el plan/);
    assert.match(splitEmptyMessage({ plan_exists: false }) ?? '', /Configura el plan/);
    assert.match(splitEmptyMessage({ plan_exists: true, status: 'no_candidates' }) ?? '', /no hay a qué repartir/);
    assert.equal(splitEmptyMessage({ plan_exists: true, status: 'ok', allocations: [] }), null);
  });

  it('valida la forma y colorea el nivel', () => {
    assert.equal(isContributionSplit({ plan_exists: true }), true);
    assert.equal(isContributionSplit({ detail: 'Not Found' }), false);
    assert.equal(levelTone(null), 'text-gray-500');
    assert.equal(levelTone(-1), 'text-amber-300');
    assert.equal(levelTone(4), 'text-teal-300');
  });
});
