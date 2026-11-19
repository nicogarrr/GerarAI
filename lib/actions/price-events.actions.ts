'use server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getT } from '@/lib/i18n/server';
import { researchRequest } from '@/lib/research/client';
import type { PriceEvent } from '@/lib/market/price-events';

export type ChartEvents = {
    events: PriceEvent[];
    averageCost: number | null;
    firstBuyDate: string | null;
    holdingNotice: string | null;
    eventsNotice: string | null;
    target: number | null;
    targetCurrency: string | null;
};

type TimelineOut = {
    events?: PriceEvent[];
    holding?: { average_cost?: number | null; first_buy_date?: string | null; notice?: string | null } | null;
    // #6009: el timeline viene acotado (500 eventos); el backend informa del
    // recorte con total/truncated/returned_* y un notice fijo. Sin estos campos
    // el aviso se descartaba y el grafico mentia por omision.
    total?: number | null;
    truncated?: boolean | null;
    returned_desde?: string | null;
    returned_hasta?: string | null;
    notice?: string | null;
};

// Texto fijo que emite el backend (company_events timeline) cuando el tramo
// viene recortado. Se sirve traducido; un aviso desconocido pasa tal cual
// (precedente: BACKEND_HOLDING_NOTICE).
const BACKEND_TIMELINE_NOTICE = 'Se muestran solo los eventos más recientes del rango. Hay eventos omitidos; el primer día mostrado puede estar incompleto. Reduce el rango de fechas para consultar el resto.';

// Texto fijo que emite el backend (company_events_service.stored_holding) cuando el coste medio no
// es comparable. Es un aviso de calidad del dato, no una etiqueta de fuente; se sirve traducido
// desde research.chart.holdingNotice y un aviso desconocido pasa tal cual (precedente: split-text).
const BACKEND_HOLDING_NOTICE = 'Coste medio no comparable: faltan cantidades/costes válidos o las divisas no coinciden. No se ha inferido un tipo de cambio.';
type TargetsOut = { currency?: string | null; consensus?: { mean?: number | null } | null };

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Eventos guardados del tramo visible del gráfico (solo base de datos, sin proveedores) y el
 * consenso de analistas que la ficha ya pide (caché del motor) para la línea de objetivo.
 */
export async function getChartEvents(ticker: string, desde: string, hasta: string): Promise<ChartEvents> {
    await requireAuthenticatedUser();
    if (!/^[A-Z0-9.^-]{1,24}$/.test(ticker) || !DAY.test(desde) || !DAY.test(hasta)) throw new Error('Rango o empresa no válido');
    const symbol = encodeURIComponent(ticker);
    const [t, timeline, targets] = await Promise.all([
        getT(),
        researchRequest<TimelineOut>(`/api/companies/${symbol}/events/timeline?desde=${desde}&hasta=${hasta}`, { timeoutMs: 12000 }).catch(() => null),
        researchRequest<TargetsOut>(`/api/companies/${symbol}/analyst-targets`, { timeoutMs: 14000 }).catch(() => null),
    ]);
    const notice = timeline?.holding?.notice ?? null;
    const events = (timeline?.events ?? []).filter((e) => e && e.date && e.source);
    // Aviso de recorte del timeline (distinto del holdingNotice: habla del
    // numero de eventos mostrados, no de la calidad del coste medio). Prioridad:
    // el texto fijo del backend traducido; un notice desconocido pasa tal cual;
    // sin notice, se compone desde total/truncated.
    const timelineNotice = timeline?.notice ?? null;
    const eventsNotice = timelineNotice === BACKEND_TIMELINE_NOTICE
        ? t('research.chart.eventsTruncatedNotice')
        : timelineNotice ?? (timeline?.truncated && typeof timeline?.total === 'number' && timeline.total > events.length
            ? t('research.chart.eventsNotice', { shown: events.length, total: timeline.total })
            : null);
    const mean = targets?.consensus?.mean;
    return {
        events,
        averageCost: timeline?.holding?.average_cost ?? null,
        firstBuyDate: timeline?.holding?.first_buy_date ?? null,
        holdingNotice: notice === BACKEND_HOLDING_NOTICE ? t('research.chart.holdingNotice') : notice,
        eventsNotice,
        target: typeof mean === 'number' && Number.isFinite(mean) && mean > 0 ? mean : null,
        targetCurrency: targets?.currency ?? null,
    };
}
