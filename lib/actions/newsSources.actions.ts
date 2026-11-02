/**
 * Multiple news sources with automatic fallback
 * Similar to dataSources but specifically for news aggregation
 */

'use server';

import { getFinnhubOnlyNews } from '@/lib/news/finnhub-only-news';
import { isFinanciallyRelevant } from '@/lib/newsRelevance';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { NewsSource } from '@/lib/types/vendorSources';

/* Ítems de cada proveedor de noticias: frontera externa sin esquema; todo
 * opcional y con fallback en el mapa. */
interface AlphaVantageFeedItem {
    time_published?: string;
    url?: string;
    title?: string;
    summary?: string;
    source?: string;
    banner_image?: string;
}

interface NewsApiArticle {
    publishedAt?: string;
    url?: string;
    title?: string;
    description?: string;
    content?: string;
    source?: { name?: string };
    urlToImage?: string;
}

interface MarketauxArticle {
    published_at?: string;
    uuid?: string;
    title?: string;
    description?: string;
    snippet?: string;
    source?: string;
    url?: string;
    image_url?: string;
}

export type { NewsSource };

/**
 * Fetch news from Finnhub: misma lógica que el fallback de getNews,
 * compartida en lib/news/finnhub-only-news. El filtro de relevancia de las
 * generales vive ahora en la fuente (el agregador lo seguía aplicando al
 * final, así que el resultado es el mismo).
 */
async function getNewsFinnhub(symbols?: string[], maxArticles = 6): Promise<MarketNewsArticle[]> {
    try {
        return await getFinnhubOnlyNews(symbols, maxArticles);
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
            .map((item: AlphaVantageFeedItem, idx: number) => {
                const timestamp = new Date(item.time_published ?? '').getTime() / 1000;
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
            .map((item: NewsApiArticle, idx: number) => {
                const timestamp = new Date(item.publishedAt ?? '').getTime() / 1000;
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
            .map((item: MarketauxArticle, idx: number) => {
                const timestamp = new Date(item.published_at ?? '').getTime() / 1000;
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
        if (!isFinanciallyRelevant(article)) continue;
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
