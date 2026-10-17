/**
 * Multiple news sources with automatic fallback
 * Similar to dataSources but specifically for news aggregation
 */

'use server';

import { validateArticle, formatArticle, getDateRange } from '@/lib/utils';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { NewsSource } from '@/lib/types/vendorSources';

export type { NewsSource };

const FINNHUB_BASE_URL = 'https://finnhub.io/api/v1';

/**
 * Fetch news from Finnhub
 */
async function getNewsFinnhub(symbols?: string[], maxArticles = 6): Promise<MarketNewsArticle[]> {
    try {
        const token = process.env.FINNHUB_API_KEY;
        if (!token) return [];

        const range = getDateRange(5);
        const cleanSymbols = (symbols || [])
            .map((s) => s?.trim().toUpperCase())
            .filter((s): s is string => Boolean(s));

        // If we have symbols, try company news
        if (cleanSymbols.length > 0) {
            const limitedSymbols = cleanSymbols.slice(0, 3);

            // Requests en paralelo: cada símbolo es independiente (fetch con
            // revalidate 60s). Mismo round-robin posterior, sin sleeps.
            const perSymbolResults = await Promise.all(
                limitedSymbols.map(async (sym) => {
                    try {
                        const url = `${FINNHUB_BASE_URL}/company-news?symbol=${encodeURIComponent(sym)}&from=${range.from}&to=${range.to}&token=${token}`;
                        const controller = new AbortController();
                        const timeoutId = setTimeout(() => controller.abort(), 8000);

                        const response = await fetch(url, {
                            next: { revalidate: 60 },
                            signal: controller.signal,
                        });

                        clearTimeout(timeoutId);

                        if (response.ok) {
                            const articles = await response.json();
                            return { sym, articles: (articles || []).filter(validateArticle) as RawNewsArticle[] };
                        }
                        return { sym, articles: [] as RawNewsArticle[] };
                    } catch {
                        return { sym, articles: [] as RawNewsArticle[] };
                    }
                }),
            );
            const perSymbolArticles: Record<string, RawNewsArticle[]> = {};
            for (const { sym, articles } of perSymbolResults) {
                perSymbolArticles[sym] = articles;
            }

            const collected: MarketNewsArticle[] = [];
            for (let round = 0; round < maxArticles; round++) {
                for (let i = 0; i < cleanSymbols.length; i++) {
                    const sym = cleanSymbols[i];
                    const list = perSymbolArticles[sym] || [];
                    if (list.length === 0) continue;
                    const article = list.shift();
                    if (!article || !validateArticle(article)) continue;
                    collected.push(formatArticle(article, true, sym, round));
                    if (collected.length >= maxArticles) break;
                }
                if (collected.length >= maxArticles) break;
            }

            if (collected.length > 0) {
                collected.sort((a, b) => (b.datetime || 0) - (a.datetime || 0));
                return collected.slice(0, maxArticles);
            }
        }

        // General market news fallback
        const generalUrl = `${FINNHUB_BASE_URL}/news?category=general&token=${token}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000);

        const response = await fetch(generalUrl, {
            next: { revalidate: 60 },
            signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) return [];

        const general = await response.json();

        const seen = new Set<string>();
        const unique: RawNewsArticle[] = [];
        for (const art of general || []) {
            if (!validateArticle(art)) continue;
            const key = `${art.id}-${art.url}-${art.headline}`;
            if (seen.has(key)) continue;
            seen.add(key);
            unique.push(art);
            if (unique.length >= 20) break;
        }

        return unique.slice(0, maxArticles).map((a, idx) => formatArticle(a, false, '', idx));
    } catch (err) {
        console.error('Finnhub news error:', err);
        return [];
    }
}

/**
 * Fetch news from Alpha Vantage
 */
async function getNewsAlphaVantage(symbols?: string[], maxArticles = 6): Promise<MarketNewsArticle[]> {
    try {
        const apiKey = process.env.ALPHA_VANTAGE_API_KEY;
        if (!apiKey) return [];

        const topics = symbols && symbols.length > 0
            ? `&tickers=${symbols.slice(0, 3).join(',')}`
            : '&topics=financial_markets';

        const url = `https://www.alphavantage.co/query?function=NEWS_SENTIMENT${topics}&apikey=${apiKey}&limit=50`;

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);

        const response = await fetch(url, {
            next: { revalidate: 60 },
            signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) return [];

        const data = await response.json();

        if (!data.feed || !Array.isArray(data.feed)) return [];

        const articles: MarketNewsArticle[] = data.feed
            .slice(0, maxArticles)
            .map((item: any, idx: number) => {
                const timestamp = new Date(item.time_published).getTime() / 1000;
                // Use hash of URL for shorter, safer IDs
                const urlHash = item.url ? item.url.split('/').pop()?.slice(0, 20) || idx : idx;
                return {
                    id: `av-${urlHash}-${idx}`,
                    headline: item.title || '',
                    summary: item.summary || '',
                    source: item.source || 'Alpha Vantage',
                    url: item.url || '',
                    image: item.banner_image || '',
                    datetime: timestamp,
                    related: symbols && symbols.length > 0 ? symbols[0] : '',
                    category: 'general',
                };
            })
            .filter((art: MarketNewsArticle) => art.headline && art.url);

        return articles;
    } catch (err) {
        console.error('Alpha Vantage news error:', err);
        return [];
    }
}

/**
 * Fetch news from NewsAPI.org
 */
async function getNewsFromNewsAPI(symbols?: string[], maxArticles = 6): Promise<MarketNewsArticle[]> {
    try {
        const apiKey = process.env.NEWSAPI_KEY;
        if (!apiKey) return [];

        // Build query - if symbols provided, search for them; otherwise use business/finance
        const query = symbols && symbols.length > 0
            ? symbols.slice(0, 3).join(' OR ')
            : 'stock market OR finance OR trading';

        const url = `https://newsapi.org/v2/everything?q=${encodeURIComponent(query)}&language=en&sortBy=publishedAt&pageSize=${maxArticles * 2}&apiKey=${apiKey}`;

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);

        const response = await fetch(url, {
            next: { revalidate: 60 },
            signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) return [];

        const data = await response.json();

        if (!data.articles || !Array.isArray(data.articles)) return [];

        const articles: MarketNewsArticle[] = data.articles
            .slice(0, maxArticles)
            .map((item: any, idx: number) => {
                const timestamp = new Date(item.publishedAt).getTime() / 1000;
                // Use hash of URL for shorter, safer IDs
                const urlHash = item.url ? item.url.split('/').pop()?.slice(0, 20) || idx : idx;
                return {
                    id: `newsapi-${urlHash}-${idx}`,
                    headline: item.title || '',
                    summary: item.description || item.content || '',
                    source: item.source?.name || 'NewsAPI',
                    url: item.url || '',
                    image: item.urlToImage || '',
                    datetime: timestamp,
                    related: symbols && symbols.length > 0 ? symbols[0] : '',
                    category: 'general',
                };
            })
            .filter((art: MarketNewsArticle) => art.headline && art.url);

        return articles;
    } catch (err) {
        console.error('NewsAPI error:', err);
        return [];
    }
}

/**
 * Fetch news from Marketaux
 */
async function getNewsMarketaux(symbols?: string[], maxArticles = 6): Promise<MarketNewsArticle[]> {
    try {
        const apiKey = process.env.MARKETAUX_API_KEY;
        if (!apiKey) return [];

        const symbolsParam = symbols && symbols.length > 0
            ? `&symbols=${symbols.slice(0, 3).join(',')}`
            : '';

        const url = `https://api.marketaux.com/v1/news/all?filter_entities=true${symbolsParam}&language=en&limit=${maxArticles}&api_token=${apiKey}`;

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);

        const response = await fetch(url, {
            next: { revalidate: 60 },
            signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) return [];

        const data = await response.json();

        if (!data.data || !Array.isArray(data.data)) return [];

        const articles: MarketNewsArticle[] = data.data
            .slice(0, maxArticles)
            .map((item: any, idx: number) => {
                const timestamp = new Date(item.published_at).getTime() / 1000;
                // Use UUID from API as it's already a unique identifier
                return {
                    id: `marketaux-${item.uuid || idx}`,
                    headline: item.title || '',
                    summary: item.description || item.snippet || '',
                    source: item.source || 'Marketaux',
                    url: item.url || '',
                    image: item.image_url || '',
                    datetime: timestamp,
                    related: symbols && symbols.length > 0 ? symbols[0] : '',
                    category: 'general',
                };
            })
            .filter((art: MarketNewsArticle) => art.headline && art.url);

        return articles;
    } catch (err) {
        console.error('Marketaux news error:', err);
        return [];
    }
}

/**
 * Get news with automatic fallback across multiple sources
 * Aggregates news from all available sources and returns the most recent
 */
export async function getNewsWithFallback(symbols?: string[], maxArticles = 6): Promise<MarketNewsArticle[]> {
    await requireAuthenticatedUser();
    const allNews: MarketNewsArticle[] = [];

    // Try to fetch from all available sources in parallel for speed
    const sources = [
        getNewsFinnhub(symbols, maxArticles),
        getNewsAlphaVantage(symbols, maxArticles),
        getNewsFromNewsAPI(symbols, maxArticles),
        getNewsMarketaux(symbols, maxArticles),
    ];

    const results = await Promise.allSettled(sources);

    // Aggregate all successful results
    results.forEach((result) => {
        if (result.status === 'fulfilled' && Array.isArray(result.value)) {
            allNews.push(...result.value);
        }
    });

    // If no news from any source, return empty
    if (allNews.length === 0) {
        return [];
    }

    // Remove duplicates based on URL
    const seen = new Set<string>();
    const unique: MarketNewsArticle[] = [];

    for (const article of allNews) {
        if (!article.url) continue;
        const normalizedUrl = article.url.toLowerCase().trim();
        if (seen.has(normalizedUrl)) continue;
        seen.add(normalizedUrl);
        unique.push(article);
    }

    // Sort by datetime (most recent first) and limit
    unique.sort((a, b) => (b.datetime || 0) - (a.datetime || 0));

    return unique.slice(0, maxArticles);
}

/**
 * Get company-specific news with fallback
 */
export async function getCompanyNewsWithFallback(symbol: string, maxArticles = 20): Promise<MarketNewsArticle[]> {
    await requireAuthenticatedUser();
    return getNewsWithFallback([symbol], maxArticles);
}
