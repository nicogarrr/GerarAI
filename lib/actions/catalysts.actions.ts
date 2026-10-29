'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type CatalystType = 'earnings' | 'dividend_ex' | 'dividend_payment' | 'filing_deadline' | 'corporate_action';

export type CatalystEvent = {
    date: string;
    ticker: string;
    type: CatalystType;
    title: string;
    detail: string | null;
    source: string;
    /** 'cartera' si es posición abierta, 'watchlist' si viene de la watchlist. */
    origin?: 'cartera' | 'watchlist';
};

export type CatalystCalendar = {
    status: 'ok' | 'partial' | 'unavailable';
    desde: string;
    hasta: string;
    held_count: number;
    /** Tickers US de la watchlist cruzados en resultados (fuera de cartera). */
    watchlist_count?: number;
    count: number;
    events: CatalystEvent[];
    errors: string[];
};

/** GET /api/calendar/catalysts — catalizadores de posiciones y watchlist (14 días por defecto). */
export async function getCatalystCalendar(): Promise<CatalystCalendar> {
    await requireAuthenticatedUser();
    return researchRequest<CatalystCalendar>('/api/calendar/catalysts');
}

export type FollowedEarningsEvent = {
    ticker: string;
    company: string;
    origin: 'cartera' | 'watchlist';
    date: string;
    /** Solo la franja que publica la fuente; nunca una hora. */
    session: 'pre_market' | 'after_market' | null;
    /** Trimestre cerrado que informa la fuente (p. ej. "Sep/2026"). */
    fiscal_label: string | null;
    /** true confirmada, false estimada, null la fuente no lo dice. */
    confirmed: boolean | null;
    source: string;
    source_url: string | null;
};

export type FollowedEarningsCalendar = {
    desde: string;
    hasta: string;
    followed_count: number;
    count: number;
    days: { date: string; events: FollowedEarningsEvent[] }[];
    without_date_in_range: string[];
    /** Subconjunto con fecha futura caducada (sin renovar): no equivale a "sin publicar". */
    stale_date_in_range?: string[];
};

/** GET /api/calendar/followed — resultados de cartera + watchlist agrupados por día (60 días). */
export async function getFollowedEarnings(options?: { desde?: string; hasta?: string }): Promise<FollowedEarningsCalendar> {
    await requireAuthenticatedUser();
    const isoDay = /^\d{4}-\d{2}-\d{2}$/;
    const params = new URLSearchParams();
    if (options?.desde && isoDay.test(options.desde)) params.set('desde', options.desde);
    if (options?.hasta && isoDay.test(options.hasta)) params.set('hasta', options.hasta);
    const query = params.size > 0 ? `?${params.toString()}` : '';
    return researchRequest<FollowedEarningsCalendar>(`/api/calendar/followed${query}`);
}

export type IpoEvent = {
    /** Ticker propuesto; null si la fuente aún no lo publica. */
    symbol: string | null;
    company: string | null;
    exchange: string | null;
    /** Fecha de salida (fijada) o prevista; null si la fuente no la da. */
    date: string | null;
    /** Precio o rango tal cual lo publica la fuente ("15.00-17.00"). */
    price: string | null;
    shares: string | null;
    offer_amount: string | null;
    /** 'upcoming' = prevista, 'priced' = precio fijado en el periodo. */
    status: 'upcoming' | 'priced';
    source: string;
};

export type IpoCalendar = {
    status: 'ok' | 'partial' | 'unavailable';
    months: string[];
    count: number;
    events: IpoEvent[];
    errors: string[];
};

/** GET /api/calendar/ipos — salidas a bolsa US del mes en curso y el siguiente (NASDAQ público). */
export async function getIpoCalendar(): Promise<IpoCalendar> {
    await requireAuthenticatedUser();
    return researchRequest<IpoCalendar>('/api/calendar/ipos');
}
