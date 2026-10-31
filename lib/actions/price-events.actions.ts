'use server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import type { PriceEvent } from '@/lib/market/price-events';

export type ChartEvents = {
    events: PriceEvent[];
    averageCost: number | null;
    firstBuyDate: string | null;
    target: number | null;
    targetCurrency: string | null;
};

type TimelineOut = { events?: PriceEvent[]; holding?: { average_cost?: number | null; first_buy_date?: string | null } | null };
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
    const [timeline, targets] = await Promise.all([
        researchRequest<TimelineOut>(`/api/companies/${symbol}/events/timeline?desde=${desde}&hasta=${hasta}`, { timeoutMs: 12000 }).catch(() => null),
        researchRequest<TargetsOut>(`/api/companies/${symbol}/analyst-targets`, { timeoutMs: 14000 }).catch(() => null),
    ]);
    const mean = targets?.consensus?.mean;
    return {
        events: (timeline?.events ?? []).filter((e) => e && e.date && e.source),
        averageCost: timeline?.holding?.average_cost ?? null,
        firstBuyDate: timeline?.holding?.first_buy_date ?? null,
        target: typeof mean === 'number' && Number.isFinite(mean) && mean > 0 ? mean : null,
        targetCurrency: targets?.currency ?? null,
    };
}
