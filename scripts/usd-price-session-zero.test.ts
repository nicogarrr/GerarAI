import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error TS5097 node requires extension
import {formatPrice,formatPercent} from '../lib/format.ts';
test('USD quoted prices use es-ES like every currency (Nico 29-oct-2026); other listings keep their currency',()=>{
 assert.equal(formatPrice(93.9,'USD'),'93,90\u00a0US$');
 assert.equal(formatPrice(214.13,'USD'),'214,13\u00a0US$');
 assert.equal(formatPrice(0.0011,'USD'),'0,0011\u00a0US$');
 assert.equal(formatPrice(93.9,'EUR'),'93,90\u00a0€');
});
test('session movement is neutral at displayed zero, missing stays missing',()=>{
 for(const n of [0,-0,0.0001,-0.0001]) assert.equal(formatPercent(n,{fromRatio:false,digits:2,signDisplay:'always'}),'0,00\u00a0%');
 assert.equal(formatPercent(null,{signDisplay:'always'}),'N/D');
 assert.equal(formatPercent(0.01,{fromRatio:false,digits:2,signDisplay:'always'}),'+0,01\u00a0%');
 assert.equal(formatPercent(-0.01,{fromRatio:false,digits:2,signDisplay:'always'}),'-0,01\u00a0%');
});
