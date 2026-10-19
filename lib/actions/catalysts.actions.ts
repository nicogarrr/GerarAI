'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type CatalystType = 'earnings' | 'dividend_ex' | 'filing_deadline' | 'corporate_action';

export type CatalystEvent = {
    date: string;
    ticker: string;
    type: CatalystType;
    title: string;
    detail: string | null;
    source: string;
    /** Solo en resultados: 'cartera' si es posición abierta, 'watchlist' si viene de la watchlist (US). */
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

/** GET /api/calendar/catalysts — catalizadores de las posiciones abiertas (14 días por defecto). */
export async function getCatalystCalendar(): Promise<CatalystCalendar> {
    await requireAuthenticatedUser();
    return researchRequest<CatalystCalendar>('/api/calendar/catalysts');
}
