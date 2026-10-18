import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { isFinanciallyRelevant } from '../lib/newsRelevance.ts';

test('general headlines about consumer topics are dropped', () => {
    assert.equal(isFinanciallyRelevant({ headline: 'I am a parenting coach: 5 tips for toddlers', summary: '' }), false);
    assert.equal(isFinanciallyRelevant({ headline: 'Helicopter makes emergency landing near river', summary: 'No injuries' }), false);
});

test('market and company headlines are kept', () => {
    assert.equal(isFinanciallyRelevant({ headline: 'Fed holds rates as inflation cools', summary: '' }), true);
    assert.equal(isFinanciallyRelevant({ headline: 'Stocks slide as chip shares fall', summary: '' }), true);
    assert.equal(isFinanciallyRelevant({ headline: 'Anything at all', summary: '', related: 'NVDA' }), true);
});

test('parenting advice is not promoted by generic financial words',()=>{
 assert.equal(isFinanciallyRelevant({headline:'A parenting coach shares tips from a CEO',summary:'CNBC Make It: investor advice for raising children'}),false);
 assert.equal(isFinanciallyRelevant({headline:'Parenting products company reports earnings growth'}),true);
});
