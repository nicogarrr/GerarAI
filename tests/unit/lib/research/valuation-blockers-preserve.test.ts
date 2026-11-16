import {expect,it} from 'vitest';
import {valuationBlockerKey,scenarioValuationCause,modelUnvaluedCauseKeys,VALUATION_BLOCKER_KEYS} from '@/lib/research/valuation-blockers';
it('does not resolve Object prototype properties as translation keys',()=>{
 for(const token of ['constructor','toString','__proto__'])expect(valuationBlockerKey(token)).toBeNull();
});
it('keeps unknown blocker visible even without a backend note',()=>{
 for(const valuation_note of [undefined,null,'','  '])expect(scenarioValuationCause({valuation_blockers:['new_machine_reason'],valuation_note},String)).toBe('new_machine_reason');
 expect(scenarioValuationCause({valuation_blockers:['forecast_missing','new_machine_reason']},String)).toContain('new_machine_reason');
});
it('preserves explanatory backend note for unknown blockers',()=>{
 expect(scenarioValuationCause({valuation_blockers:['future'],valuation_note:'Source details'},String)).toBe('Source details');
 expect(scenarioValuationCause({valuation:{}},String)).toBeNull();
 expect(scenarioValuationCause({},String)).toBeNull();
 expect(scenarioValuationCause({valuation_note:'Reason'},String)).toBe('Reason');
});
it('translates actual backend tokens and dedupes known header keys',()=>{
 for(const token of Object.keys(VALUATION_BLOCKER_KEYS))expect(scenarioValuationCause({valuation_blockers:[token]},String)).toBe(VALUATION_BLOCKER_KEYS[token]);
 expect(modelUnvaluedCauseKeys({})).toEqual([]);
 expect(modelUnvaluedCauseKeys({x:{valuation:0}})).toEqual([]);
 expect(modelUnvaluedCauseKeys({x:{valuation_blockers:['forecast_missing','unknown']},y:{valuation_blockers:['forecast_missing']},z:{}})).toEqual([VALUATION_BLOCKER_KEYS.forecast_missing]);
});
