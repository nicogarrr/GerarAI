import { withAuthErrors } from '@/lib/auth/route-auth';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getHomeWatchlistPreview, type HomeWatchlistItem } from '@/lib/actions/home-overview.actions';
import { sectionResponse } from '@/lib/home/section-response';
import type { NextRequest } from 'next/server';

// Mismo tope que la tarjeta del inicio (WATCHLIST_PREVIEW_LIMIT): el resto
// de la watchlist es un contador y un enlace, no filas anónimas.
const DEFAULT_LIMIT = 3;
const MAX_LIMIT = 24;

/** Sección Watchlist del inicio: vista previa cotizada con batch + presupuesto. */
async function getHandler(request: NextRequest) {
    await requireAuthenticatedUser();
    const parsed = Number(request.nextUrl.searchParams.get('limit') ?? '');
    const limit = Number.isSafeInteger(parsed) && parsed >= 1 && parsed <= MAX_LIMIT ? parsed : DEFAULT_LIMIT;
    return sectionResponse(
        () => getHomeWatchlistPreview(limit).then((preview) => {
            // Mensaje interno (la copia la resuelve el cliente con t() via sectionErrorKey).
            if (preview.unavailable) throw new Error('watchlist unavailable');
            return preview;
        }),
        { unavailable: false, total: 0, items: [] as HomeWatchlistItem[] },
    );
}

export const GET = withAuthErrors(getHandler);
