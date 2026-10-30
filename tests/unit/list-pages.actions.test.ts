import { beforeEach, describe, expect, it, vi } from 'vitest';
const { request, identity, user } = vi.hoisted(() => ({ request: vi.fn(), identity: vi.fn(), user: vi.fn() }));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/lib/auth/research-identity', () => ({ normalizeResearchBody: () => ({ body: null }), researchIdentityHeaders: identity }));
vi.mock('@/lib/research/client', () => ({ RESEARCH_TIMEOUTS: { GLOBAL_MS: 1000 }, requestSignal: () => undefined, researchRequest: request }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: user }));
import { getKnowledgeLibrary, getKnowledgeDocument } from '@/lib/actions/research-tools.actions';
import { getPortfolioTransactionPage } from '@/lib/actions/portfolio.actions';

describe('bounded page actions', () => {
 beforeEach(() => { vi.clearAllMocks(); user.mockResolvedValue({ id: 'tenant-one' }); identity.mockResolvedValue({}); });
 it('requests a bounded offset page and server-side principle status, preserving totals', async () => {
  const urls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
   urls.push(String(url));
   const payload = url.includes('/documents/page') ? { items: [{ id: 1 }], total: 351, collection_counts: { 3: 351 } }
    : url.includes('/principles/page') ? { items: [{ id: 8, status: 'approved' }], total: 1, proposed_total: 350 } : [];
   return new Response(JSON.stringify(payload));
  }));
  const result = await getKnowledgeLibrary({ documentOffset: 200, principleOffset: 0, status: 'approved' });
  expect(urls.some(url => url.endsWith('/documents/page?limit=50&offset=200'))).toBe(true);
  expect(urls.some(url => url.endsWith('/principles/page?limit=50&offset=0&status=approved'))).toBe(true);
  expect(result.documentTotal).toBe(351); expect(result.proposedTotal).toBe(350);
  expect(result.documents).toHaveLength(1); expect(result.principles).toHaveLength(1);
 });
 it('searches the library in the backend (tenant-scoped endpoint) and keeps library totals', async () => {
  const urls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
   urls.push(String(url));
   const payload = url.includes('/documents/search') ? { items: [{ id: 7 }], total: 61, query: 'buffett carta' }
    : url.includes('/documents/page') ? { items: [{ id: 1 }], total: 351, collection_counts: { 3: 351 } }
    : url.includes('/principles/page') ? { items: [], total: 0, proposed_total: 0 } : [];
   return new Response(JSON.stringify(payload));
  }));
  const result = await getKnowledgeLibrary({ documentOffset: 50, q: '  buffett carta ' });
  expect(urls.some(url => url.endsWith('/documents/search?q=buffett%20carta&limit=50&offset=50'))).toBe(true);
  expect(result.documents).toEqual([{ id: 7 }]);
  expect(result.documentSearch).toEqual({ query: 'buffett carta', total: 61 });
  expect(result.documentTotal).toBe(351);
  urls.length = 0;
  expect((await getKnowledgeLibrary({ q: '   ' })).documentSearch).toBeNull();
  expect(urls.some(url => url.includes('/documents/search'))).toBe(false);
 });
 it('resolves a document outside the visible page and keeps missing links harmless', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ id: 1, title: 'Old document' })))
   .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 }));
  vi.stubGlobal('fetch', fetch);
  expect((await getKnowledgeDocument(1))?.title).toBe('Old document');
  expect(await getKnowledgeDocument(999)).toBeNull();
  expect(String(fetch.mock.calls[0][0])).toContain('/documents/1');
 });
 it('maps the 201st transaction with its currency and does not cache stale pages', async () => {
  request.mockResolvedValue({ items: [{ id: 201, ticker: 'OLD', action: 'buy', quantity: 1, price: 10, fees: 2.5, trade_date: '2020-01-01', currency: 'EUR' }], total: 201 });
  const page = await getPortfolioTransactionPage('tenant-one', 200);
  expect(page).toMatchObject({ total: 201, offset: 200, items: [{ _id: '201', currency: 'EUR', fees: 2.5 }] });
  expect(request).toHaveBeenCalledWith('/api/portfolio/transactions/page?limit=50&offset=200', { fast: true });
  await getPortfolioTransactionPage('tenant-one', 200); expect(request).toHaveBeenCalledTimes(2);
 });
 it('rejects cross-user reads before requesting a page', async () => {
  await expect(getPortfolioTransactionPage('tenant-two', 200)).rejects.toThrow('Cannot access another user portfolio');
  expect(request).not.toHaveBeenCalled();
 });
 it('does not invent zero fees when metadata is absent', async () => {
  request.mockResolvedValue({ items: [{ id: 201, ticker: 'OLD', action: 'buy', quantity: 1, price: 10, trade_date: '2020-01-01', currency: 'EUR' }], total: 201 });
  expect((await getPortfolioTransactionPage('tenant-one', 200)).items[0].fees).toBeUndefined();
 });
});
