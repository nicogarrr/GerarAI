import NewsSection from '@/components/NewsSection';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';

/**
 * Noticias de Inicio: solo de la cartera del usuario (decisión 29-oct-2026,
 * vista Noticias por acción). Degradación honesta: sin cartera, lista general
 * como antes. Los tickers se leen DENTRO del <Suspense> de las noticias: antes
 * la página entera esperaba a leer todas las posiciones y la watchlist antes
 * del primer byte, aunque solo las usa esta sección del final.
 */
export async function PortfolioNews() {
    const { portfolioTickers } = await getTickerContext().catch(() => ({ portfolioTickers: [] as string[], watchlistTickers: [] as string[] }));
    return <NewsSection symbols={portfolioTickers.length ? portfolioTickers : undefined} />;
}
