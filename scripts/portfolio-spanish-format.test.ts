import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
test('corporate action structured money and dates use display formatters',()=>{
 const s=readFileSync('components/corporate-actions/CorporateActionsView.tsx','utf8');
 assert.ok(s.includes('formatMoney(record.amount_per_share, record.currency)'));
 assert.ok(s.includes('effective_date: (value) => formatMarketDate'));
 assert.ok(s.includes('formatMarketDate(record.pay_date as string)'));
});
test('forecast and dividend Spanish prose has no raw excluded token or lost accents',()=>{
 const s=readFileSync('data-engine/app/api/routes/portfolio.py','utf8');
 assert.ok(!s.includes('se lista en excluded'));
 assert.ok(s.includes('se lista en las excluidas'));
 const d=readFileSync('data-engine/app/services/dividend_projection_service.py','utf8');
 assert.ok(d.includes('este año carecen de tipo de cambio o de retención'));
});
