'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type CalendarFeedScope = 'followed' | 'watchlist';

export type CalendarFeedState = {
    active: boolean;
    scope: CalendarFeedScope | null;
    created_at: string | null;
    last_used_at: string | null;
};

export type CalendarFeedCreated = {
    /** Solo se devuelve UNA vez, al crearlo: el backend nunca lo vuelve a mostrar. */
    token: string;
    path: string;
};

/** GET /api/calendar/feed — estado de la suscripción (nunca incluye el token). */
export async function getCalendarFeed(): Promise<CalendarFeedState> {
    await requireAuthenticatedUser();
    return researchRequest<CalendarFeedState>('/api/calendar/feed');
}

/** POST /api/calendar/feed — crea (y revoca la anterior) la suscripción. */
export async function createCalendarFeed(scope: CalendarFeedScope): Promise<CalendarFeedCreated> {
    await requireAuthenticatedUser();
    return researchRequest<CalendarFeedCreated>('/api/calendar/feed', {
        method: 'POST',
        body: JSON.stringify({ scope }),
    });
}

/** DELETE /api/calendar/feed — revoca la suscripción activa. */
export async function revokeCalendarFeed(): Promise<{ revoked: boolean }> {
    await requireAuthenticatedUser();
    return researchRequest<{ revoked: boolean }>('/api/calendar/feed', { method: 'DELETE' });
}
