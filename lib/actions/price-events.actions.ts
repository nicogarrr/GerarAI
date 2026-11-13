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
    target: number | null;
    targetCurrency: string | null;
};

type TimelineOut = { events?: PriceEvent[]; holding?: { average_cost?: number | null; first_buy_date?: string | null; notice?: string | null } | null };

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
    const mean = targets?.consensus?.mean;
    return {
        events: (timeline?.events ?? []).filter((e) => e && e.date && e.source),
        averageCost: timeline?.holding?.average_cost ?? null,
        firstBuyDate: timeline?.holding?.first_buy_date ?? null,
        holdingNotice: notice === BACKEND_HOLDING_NOTICE ? t('research.chart.holdingNotice') : notice,
        target: typeof mean === 'number' && Number.isFinite(mean) && mean > 0 ? mean : null,
        targetCurrency: targets?.currency ?? null,
    };
}
