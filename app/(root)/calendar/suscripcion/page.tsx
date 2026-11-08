import type { Metadata } from 'next';
import { headers } from 'next/headers';

import BackendOffline from '@/components/system/BackendOffline';
import SubscriptionManager from '@/components/calendar/SubscriptionManager';
import { getCalendarFeed, type CalendarFeedState } from '@/lib/actions/calendar-feed.actions';
import { AppError } from '@/lib/types/errors';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const ti = await getT();
    return {
        title: ti('calendar.meta.subscriptionTitle'),
        description: ti('calendar.meta.subscriptionDescription'),
    };
}

const EMPTY: CalendarFeedState = { active: false, scope: null, created_at: null, last_used_at: null };

const PRODUCTION_HOST = 'gerarai.duckdns.org';
const DEFAULT_ORIGIN = `https://${PRODUCTION_HOST}`;
// Dominio propio detrás de Caddy + hosts locales de desarrollo. Otro despliegue
// debe fijar NEXT_PUBLIC_SITE_URL.
const TRUSTED_HOSTS = new Set([PRODUCTION_HOST, 'localhost', 'localhost:3000', '127.0.0.1', '127.0.0.1:3000']);

export default async function CalendarSubscriptionPage() {
    const ti = await getT();
    let state: CalendarFeedState;
    try {
        state = await getCalendarFeed();
    } catch (error) {
        // 404 = backend aún sin el endpoint de feed: mismo trato que caído.
        const unavailable =
            isBackendUnavailableError(error) ||
            (error instanceof AppError && error.code === 'RESEARCH_API_ERROR' && error.statusCode === 404);
        if (unavailable) {
            return <BackendOffline feature={ti('calendar.subscription.offlineFeature')} retryHref="/calendar/suscripcion" />;
        }
        throw error;
    }

    const envOrigin = process.env.NEXT_PUBLIC_SITE_URL || process.env.BETTER_AUTH_URL;
    let origin: string;
    if (envOrigin) {
        origin = envOrigin.replace(/\/+$/, '');
    } else {
        // El enlace de suscripción lleva el token del feed en la URL: si el host
        // saliera de una cabecera controlable por el cliente (Caddy reenvía el
        // Host original), el enlace apuntaría a un dominio ajeno. Solo se acepta
        // el dominio propio o un host local de desarrollo; cualquier otro cae al
        // dominio propio.
        const headerList = await headers();
        const rawHost = headerList.get('x-forwarded-host') ?? headerList.get('host') ?? '';
        const host = rawHost.split(',')[0].trim().toLowerCase();

        const rawProto = headerList.get('x-forwarded-proto') ?? 'https';
        const protoFirst = rawProto.split(',')[0].trim().toLowerCase();
        const proto = protoFirst === 'http' || protoFirst === 'https' ? protoFirst : 'https';
        if (!TRUSTED_HOSTS.has(host)) {
            origin = DEFAULT_ORIGIN;
        } else if (host === PRODUCTION_HOST) {
            // El dominio propio va siempre en https (Caddy termina TLS): el
            // enlace con token nunca sale en claro aunque la cabecera mienta.
            origin = `https://${PRODUCTION_HOST}`;
        } else {
            // Desarrollo local: se respeta el proto de la cabecera (http).
            origin = `${proto}://${host}`;
        }
    }

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-2xl flex-col gap-6">
            <header className="flex flex-col gap-1">
                <h1 className="text-2xl font-bold text-gray-100">{ti('calendar.subscription.pageTitle')}</h1>
            </header>
            <SubscriptionManager initialState={state ?? EMPTY} origin={origin} />
        </main>
    );
}
