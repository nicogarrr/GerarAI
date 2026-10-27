// @vitest-environment node
import { describe, expect, it, vi, beforeEach } from 'vitest';
const mocks = vi.hoisted(() => ({ candles: vi.fn(), request: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn() }));
vi.mock('@/lib/actions/market-workspace.actions', () => ({ getResearchCompanyBasics: vi.fn().mockResolvedValue({ticker:'DEMO.L', currency:'GBP', exchange:'LSE'}) }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getCandles: mocks.candles }));
vi.mock('@/lib/market/quote-symbol', () => ({ quoteSymbolFor: () => 'DEMO.L' }));
vi.mock('@/lib/research/client', () => ({ researchRequest: mocks.request }));
import { getCompanyChartHistory } from '@/lib/actions/company-chart.actions';
import { fetchDatedChanges } from '@/lib/market/dated-change';
import { normalizeChartPriceUnits } from '@/lib/market/chart-price-units';

describe('unit metadata transport across server actions', () => {
 beforeEach(() => { vi.stubEnv('E2E_MARKET_FIXTURE','0'); });
 it.each(['1D','5D','5A','Máx'])('preserves response currency for remote %s range', async range => {
  const timestamp = Math.floor(Date.now()/1000)-3600;
  mocks.candles.mockResolvedValue({s:'ok',currency:'GBp',source:'synthetic',t:[timestamp],c:[4300],o:[4200],h:[4400],l:[4100],v:[10]});
  const result = await getCompanyChartHistory('DEMO.L',range);
  expect(result.currency).toBe('GBp');
  expect(result.bars.length).toBe(1);
  const normalized = normalizeChartPriceUnits(result.bars,{ticker:'DEMO.L',currency:'GBP',candleCurrency:result.currency});
  expect(normalized.currency).toBe('GBP');
  expect(normalized.bars[0].close).toBe(43);
 });
 it('preserves the major unit associated with dated normalized prices', async () => {
  mocks.request.mockResolvedValue({items:{'DEMO.L':{price:43,currency:'GBP',change:1,change_pct:100/42,previous_close:42,date:'2026-10-27'}}});
  expect((await fetchDatedChanges(['DEMO.L']))['DEMO.L']).toMatchObject({price:43,currency:'GBP',previousClose:42});
 });
});
