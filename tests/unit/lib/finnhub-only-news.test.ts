import { afterEach, describe, expect, it, vi } from 'vitest';
const { fetchJSON } = vi.hoisted(() => ({ fetchJSON: vi.fn() }));
vi.mock('@/lib/upstream/finnhub', () => ({ fetchJSON }));
import { getFinnhubOnlyNews } from '@/lib/news/finnhub-only-news';
const article = (id: number, headline = 'Apple beats earnings expectations') => ({ id, headline, summary: 'Apple stock rises after strong revenue.', url: `https://news.example/${id}`, datetime: 1700000000 + id, source: 'Reuters', image: '' });
afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs(); });
describe('shared Finnhub news', () => {
    it('does not call a provider without its key', async () => {
        vi.stubEnv('FINNHUB_API_KEY', '');
        expect(await getFinnhubOnlyNews(['AAPL'])).toEqual([]);
        expect(fetchJSON).not.toHaveBeenCalled();
    });
    it('limits company requests to three symbols and tolerates one provider failure', async () => {
        vi.stubEnv('FINNHUB_API_KEY', 'fixture-token');
        fetchJSON.mockImplementation(async (url: string) => {
            if (url.includes('MSFT')) throw new Error('fixture rate limit');
            return [article(url.includes('AAPL') ? 1 : 3)];
        });
        const news = await getFinnhubOnlyNews([' aapl ', 'MSFT', 'GOOG', 'NVDA']);
        expect(fetchJSON).toHaveBeenCalledTimes(3);
        expect(fetchJSON.mock.calls.every(([url, ttl]) => String(url).includes('/company-news?') && ttl === 60)).toBe(true);
        expect(news.map((x) => x.datetime)).toEqual([1700000003, 1700000001]);
    });
    it('falls back to general news, filters irrelevant items before the final limit, and deduplicates', async () => {
        vi.stubEnv('FINNHUB_API_KEY', 'fixture-token');
        fetchJSON.mockImplementation(async (url: string) => url.includes('/company-news?') ? [] : [{ ...article(1, 'Celebrity wedding photos'), summary: 'The guests arrive at the ceremony.' }, article(2), article(2), article(3)]);
        const news = await getFinnhubOnlyNews(['AAPL'], 2);
        expect(news).toHaveLength(2);
        expect(new Set(news.map((x) => x.url)).size).toBe(2);
        expect(news.every((x) => x.headline.includes('Apple'))).toBe(true);
    });
});
