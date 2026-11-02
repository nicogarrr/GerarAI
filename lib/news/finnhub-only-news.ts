/**
 * Noticias solo-Finnhub: por empresa (round-robin entre símbolos) o generales
 * de mercado con filtro de relevancia financiera y deduplicado.
 *
 * Lo comparten las dos rutas que antes llevaban cada una su copia:
 *  - el fallback de getNews (lib/actions/finnhub.actions.ts), cuando el
 *    agregador multi-fuente vuelve vacío;
 *  - la fuente Finnhub del propio agregador (lib/actions/newsSources.actions.ts).
 *
 * Módulo interno SIN 'use server', por el mismo motivo que
 * lib/upstream/finnhub.ts: en un fichero 'use server' todo export se
 * registra como Server Action invocable por HTTP, y aquí se construyen URLs.
 */

import { fetchJSON } from '@/lib/upstream/finnhub';
import { isFinanciallyRelevant } from '@/lib/newsRelevance';
import { formatArticle, getDateRange, validateArticle } from '@/lib/utils';
import { env } from '@/lib/env';

const FINNHUB_BASE_URL = env.FINNHUB_BASE_URL;

export async function getFinnhubOnlyNews(symbols: string[] | undefined, maxArticles = 6): Promise<MarketNewsArticle[]> {
    // process.env a propósito (no el singleton de @/lib/env): la clave puede
    // fijarse en caliente y los tests la cambian entre casos sin reimportar.
    const token = process.env.FINNHUB_API_KEY;
    if (!token) {
        // Sin fuente de noticias configurada no es un fallo: es «no hay
        // noticias». Antes se lanzaba, Inicio pintaba el aviso ámbar «No se
        // pudieron cargar las noticias» con un «Reintentar» que no podía
        // arreglar nada, y el error salía en la consola del navegador.
        return [];
    }
    const range = getDateRange(5);
    const cleanSymbols = (symbols || [])
        .map((s) => s?.trim().toUpperCase())
        .filter((s): s is string => Boolean(s));

    // Con símbolos, noticias de empresa en paralelo y selección round-robin.
    // Limitar a máximo 3 símbolos para evitar rate limiting.
    if (cleanSymbols.length > 0) {
        const limitedSymbols = cleanSymbols.slice(0, 3);
        const perSymbolResults = await Promise.all(
            limitedSymbols.map(async (sym) => {
                try {
                    const url = `${FINNHUB_BASE_URL}/company-news?symbol=${encodeURIComponent(sym)}&from=${range.from}&to=${range.to}&token=${token}`;
                    // Noticias siempre frescas - máximo 60 segundos de cache
                    const articles = await fetchJSON<RawNewsArticle[]>(url, 60);
                    return { sym, articles: (articles || []).filter(validateArticle) };
                } catch {
                    // Silenciar errores 429 (rate limit): ese símbolo aporta []
                    // y el resto continúa; el fallback a generales sigue abajo.
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
        // Sin noticias de empresa: cae a las generales.
    }

    // Noticias generales de mercado, filtrando relevancia financiera y
    // duplicados. En la ruta del agregador multi-fuente el filtro ya se
    // aplicaba al final (mismo resultado); aquí queda en la fuente.
    const generalUrl = `${FINNHUB_BASE_URL}/news?category=general&token=${token}`;
    const general = await fetchJSON<RawNewsArticle[]>(generalUrl, 60);

    const seen = new Set<string>();
    const unique: RawNewsArticle[] = [];
    for (const art of general || []) {
        if (!validateArticle(art) || !isFinanciallyRelevant(art)) continue;
        const key = `${art.id}-${art.url}-${art.headline}`;
        if (seen.has(key)) continue;
        seen.add(key);
        unique.push(art);
        if (unique.length >= 20) break; // cap temprano antes del corte final
    }

    return unique.slice(0, maxArticles).map((a, idx) => formatArticle(a, false, undefined, idx));
}
