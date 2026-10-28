import { describe, expect, it } from 'vitest';
import { brainHandoffContext, knowledgeHandoff } from '@/lib/brain/open-brain';

describe('brain handoff context replacement', () => {
  it('AAPL review 1 does not leak into a new ticker without review_id', () => {
    let context = brainHandoffContext({ ticker: 'AAPL', review_id: 1 });
    expect(context).toEqual({ ticker: 'AAPL', reviewId: 1 });
    context = brainHandoffContext({ ticker: 'MSFT', question: 'deuda' });
    expect(context).toEqual({ ticker: 'MSFT', reviewId: undefined });
  });
  it('an empty or tickerless shortcut resets both fields', () => {
    for (const detail of [undefined, null, {}, { question: 'cartera' }, { review_id: 1 }]) {
      expect(brainHandoffContext(detail)).toEqual({ ticker: '', reviewId: undefined });
    }
  });
  it('rejects invalid tickers and invalid review IDs', () => {
    expect(brainHandoffContext({ ticker: '../AAPL', review_id: 1 })).toEqual({ ticker: '', reviewId: undefined });
    for (const review_id of [0, -1, 1.2, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      expect(brainHandoffContext({ ticker: 'aapl', review_id })).toEqual({ ticker: 'AAPL', reviewId: undefined });
    }
  });
  it('keeps an explicitly supplied valid review on the new ticker', () => {
    expect(brainHandoffContext({ ticker: 'msft', review_id: 2 })).toEqual({ ticker: 'MSFT', reviewId: 2 });
  });
});

describe('knowledge handoff validation', () => {
 it('accepts only supported scopes and bounded author names', () => {
  expect(knowledgeHandoff({knowledge:{scope:'library',authors:['Buffett']}})).toEqual({scope:'library',authors:['Buffett']});
  expect(knowledgeHandoff({ticker:'UBER'})).toBeNull();
  expect(knowledgeHandoff({knowledge:{scope:'other'} as never})).toBeNull();
 });
});
