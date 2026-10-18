import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error Explicit TS extension for node strip types.
import { extractionResultText, hasDefaultCollections } from '../lib/knowledge/job-feedback.ts';
test('completed zero, recorded count, partial and errors are distinct', () => {
  assert.match(extractionResultText({status:'completed',result:{principle_ids:[]},error:null})!, /0 principios/);
  assert.match(extractionResultText({status:'partial',result:{principle_ids:[2,3]},error:null})!, /parcial: 2 principios/);
  assert.match(extractionResultText({status:'completed',result:{},error:null})!, /Recuento no disponible/);
  assert.match(extractionResultText({status:'failed',result:{},error:null})!, /No se pudo/);
  assert.equal(extractionResultText({status:'running',result:{},error:null}), null);
});
test('one default does not mean all defaults are installed', () => {
  assert.equal(hasDefaultCollections([{name:'Buffett & Munger'}]), false);
  assert.equal(hasDefaultCollections(['Buffett & Munger','Howard Marks','Fundsmith','Numantia','Capital Allocation','Cyclicals','Compounders','Pre-revenue','Space Industry','Personal Mistakes'].map(name=>({name}))), true);
});
