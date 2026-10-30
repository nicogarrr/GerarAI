import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
test('company results participate in cmdk selection before section shortcuts',()=>{
 const s=readFileSync('components/SearchCommand.tsx','utf8')+readFileSync('components/SearchCommandDialog.tsx','utf8');
 assert.ok(s.includes('value={`stock:${stock.symbol}`}'));
 assert.ok(s.includes('setSelectedValue(result.stocks[0]'));
 assert.ok(s.indexOf('value={`stock:${stock.symbol}`}') < s.indexOf('value={`ir ${label}`}'));
 assert.ok(s.includes('label: t(item.labelKey)'));
 assert.ok(s.includes('commandProps={{shouldFilter:false'));
 assert.ok(!s.includes('onClick={() => handleSelectStock'));
});
test('unsupported search input returns empty success before network request',()=>{
 const s=readFileSync('lib/actions/finnhub.actions.ts','utf8');
 const body=s.slice(s.indexOf('export const searchStocksWithStatus'));
 assert.ok(body.indexOf('query.length > 120')<body.indexOf('searchStocksOrThrow(query)'));
 assert.ok(body.includes("return { status: 'ok', stocks: [] }"));
});
