import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
test('missing stress tickers keep their contextual label and dates are localized',()=>{
 const s=readFileSync('components/historical-stress/HistoricalStressView.tsx','utf8');
 assert.ok(s.includes("Sin histórico suficiente: {window.missing_tickers.join(', ')}"));
 assert.ok(s.includes('formatMarketDate(value)'));
});
test('sizing contribution is not labeled as position size',()=>{
 assert.ok(readFileSync('lib/labels.ts','utf8').includes("sizing: 'Contribución ponderada'"));
 const backend=readFileSync('data-engine/app/services/portfolio_intelligence_service.py','utf8');
 assert.ok(backend.includes("total_return * weights.get(company.id, 0)"));
});
