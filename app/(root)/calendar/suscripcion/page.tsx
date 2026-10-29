import type { Metadata } from 'next';
import { headers } from 'next/headers';

import BackendOffline from '@/components/system/BackendOffline';
import SubscriptionManager from '@/components/calendar/SubscriptionManager';
import { getCalendarFeed, type CalendarFeedState } from '@/lib/actions/calendar-feed.actions';
import { AppError } from '@/lib/types/errors';
import { isBackendUnavailableError } from '@/lib/backend-offline';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Suscripción al calendario',
    description: 'Recibe los resultados de tus empresas en Apple, Google u Outlook Calendar.',
};

const EMPTY: CalendarFeedState = { active: false, scope: null, created_at: null, last_used_at: null };

export default async function CalendarSubscriptionPage() {
    let state: CalendarFeedState;
    try {
        state = await getCalendarFeed();
    } catch (error) {
        // 404 = backend aún sin el endpoint de feed: mismo trato que caído.
        const unavailable =
            isBackendUnavailableError(error) ||
            (error instanceof AppError && error.code === 'RESEARCH_API_ERROR' && error.statusCode === 404);
        if (unavailable) {
            return <BackendOffline feature="Suscripción al calendario" retryHref="/calendar/suscripcion" />;
        }
        throw error;
    }

    const envOrigin = process.env.NEXT_PUBLIC_SITE_URL || process.env.BETTER_AUTH_URL;
    let origin: string;
    if (envOrigin) {
        origin = envOrigin.replace(/\/+$/, '');
    } else {
        const headerList = await headers();
        const rawHost = headerList.get('x-forwarded-host') ?? headerList.get('host') ?? 'gerarai.vercel.app';
        const hostFirst = rawHost.split(',')[0].trim();
        const host = /^[a-zA-Z0-9.-]+(:\d+)?$/.test(hostFirst) ? hostFirst : 'gerarai.vercel.app';

        const rawProto = headerList.get('x-forwarded-proto') ?? 'https';
        const protoFirst = rawProto.split(',')[0].trim().toLowerCase();
        const proto = protoFirst === 'http' || protoFirst === 'https' ? protoFirst : 'https';
        origin = `${proto}://${host}`;
    }

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-2xl flex-col gap-6">
            <header className="flex flex-col gap-1">
                <h1 className="text-2xl font-bold text-gray-100">Suscripción al calendario</h1>
                <p className="text-sm text-gray-400">
                    Resultados de tus empresas directamente en Apple, Google u Outlook Calendar.
                </p>
            </header>
            <SubscriptionManager initialState={state ?? EMPTY} origin={origin} />
        </main>
    );
}
