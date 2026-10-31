'use server';

import { getPortfolioSummary, type PortfolioSummary } from '@/lib/actions/portfolio.actions';
import {
    getRecentTriggeredAlerts,
    getUserAlerts,
    type Alert,
    type TriggeredAlertDelivery,
} from '@/lib/actions/alerts.actions';
import {
    getHomeWatchlistPreview,
    type HomeWatchlistPreview,
} from '@/lib/actions/home-overview.actions';
import { sectionErrorKey } from '@/lib/section-error';

/**
 * Primera carga del inicio en UNA server action.
 *
 * Next ejecuta en serie las server actions que lanza un mismo cliente: las
 * tres secciones rápidas del inicio (cartera, alertas, watchlist) eran POST
 * encadenados y el contenido esperaba a la suma. Aquí las lecturas corren a
 * la vez en el servidor y llegan en un solo viaje. Cada sección conserva su
 * propio resultado y su propio error (un fallo no tumba a las demás); los
 * «Reintentar» siguen usando la lectura suelta.
 *
 * OPORTUNIDADES NO VIAJA EN ESTE POST: su sondeo DCF cotiza candidatas con
 * proveedores externos en síncrono (~7 s medidos en prod, 31-oct) y, al
 * compartir promesa, obligaba a las tres secciones rápidas a esperar esos
 * ~7 s antes de pintar (skeletons persistentes en Inicio) además de quemar
 * Fluid Active CPU de Vercel en el primer pintado. La sección se pide
 * DESPUÉS del primer pintado con su propia llamada (debajo del pliegue).
 */

export type HomeSection<T> = { data: T; error: string | null };

export type HomeOverviewBundle = {
    portfolio: HomeSection<PortfolioSummary | null>;
    alerts: HomeSection<{ rules: Alert[]; triggered: TriggeredAlertDelivery[] }>;
    watchlist: HomeSection<HomeWatchlistPreview>;
};

async function section<T>(read: () => Promise<T>, fallback: T): Promise<HomeSection<T>> {
    try {
        return { data: await read(), error: null };
    } catch (error) {
        // Solo la clave genérica por categoría viaja al cliente; el texto lo
        // resuelve el cliente con t() en el idioma activo.
        return { data: fallback, error: sectionErrorKey(error) };
    }
}

export async function getHomeOverviewBundle(
    userId: string,
    params: { watchlistLimit: number },
): Promise<HomeOverviewBundle> {
    const [portfolio, alerts, watchlist] = await Promise.all([
        section(() => getPortfolioSummary(userId), null as PortfolioSummary | null),
        section(
            () => Promise.all([getUserAlerts(), getRecentTriggeredAlerts(3)]).then(([rules, triggered]) => ({ rules, triggered })),
            { rules: [] as Alert[], triggered: [] as TriggeredAlertDelivery[] },
        ),
        section(
            () => getHomeWatchlistPreview(params.watchlistLimit).then((preview) => {
                if (preview.unavailable) throw new Error('No se pudo cargar la watchlist');
                return preview;
            }),
            { unavailable: false, total: 0, items: [] } as HomeWatchlistPreview,
        ),
    ]);
    return { portfolio, alerts, watchlist };
}
