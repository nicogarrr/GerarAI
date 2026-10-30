import type { Metadata } from 'next';
import { Suspense } from 'react';

import PersonalizedOverview from '@/components/PersonalizedOverview';
import EarningsDayStrip from '@/components/calendar/EarningsDayStrip';
import NewsSection from '@/components/NewsSection';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';
import { NewsLoadingSkeleton } from '@/components/LoadingState';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { redirectToSignIn } from '@/lib/auth/sign-in-redirect';
import { getT } from '@/lib/i18n/server';

// Forzar renderizado dinámico porque requiere datos de usuario
export const dynamic = 'force-dynamic';
export const revalidate = 0;

// La home es la raíz ("/"): el template de app/layout.tsx ("%s | GerarAI")
// repetiría la marca, así que el título va absoluto.
export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
        title: { absolute: t('home.metadata.title') },
        description: t('home.metadata.description'),
    };
}

async function getUserId(): Promise<string> {
    try {
        return (await requireAuthenticatedUser()).id;
    } catch {
        return redirectToSignIn();
    }
}

export default async function Home() {
    const userId = await getUserId();
    // Noticias de Inicio: solo de la cartera del usuario (decisión 29-oct-2026,
    // vista Noticias por acción). Degradación honesta: sin cartera, lista
    // general como antes.
    const { portfolioTickers } = await getTickerContext().catch(() => ({ portfolioTickers: [] as string[], watchlistTickers: [] as string[] }));

    return (
        <main id="content" tabIndex={-1} className="flex w-full max-w-full min-w-0 flex-col gap-6 overflow-x-clip sm:gap-8">
            {/*
                PersonalizedOverview no lleva <Suspense>: es un client component
                que pinta sus propios esqueletos, así que el fallback de servidor
                era código muerto (nunca se veía) y retrasaba el LCP. El único
                estado de carga de esta página es, por tanto, el de las secciones.

                NewsSection sí es un server component async: su <Suspense> es
                real y deja que las noticias lleguen por streaming al final del
                scroll, sin bloquear el resto del dashboard.
            */}
            {/* El calendario (logos grandes, lectura rápida) va entre Alertas y
                Watchlist: PersonalizedOverview lo pinta en su sitio. */}
            <PersonalizedOverview
                userId={userId}
                afterAlerts={(
                    <Suspense fallback={null}>
                        <EarningsDayStrip />
                    </Suspense>
                )}
            />
            <Suspense fallback={<NewsLoadingSkeleton />}>
                <NewsSection symbols={portfolioTickers.length ? portfolioTickers : undefined} />
            </Suspense>
        </main>
    );
}
