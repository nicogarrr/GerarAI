'use server';

import { researchRequest } from '@/lib/research/client';
import { getResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';

/**
 * Consenso de precios objetivo por analista para listas (watchlist/cartera).
 *
 * Fuente gratuita y NO oficial (Yahoo Finance, agregado de analistas): la
 * celda declara fuente y hora de obtención, la divisa es la declarada por
 * Yahoo para el listado consultado (o número pelado si no la declara) y un
 * fallo o una ausencia devuelven estado, nunca cifras inventadas.
 */
export type ListingAnalystTargets = {
    status: 'available' | 'empty' | 'unavailable';
    /** Media del consenso; null sin consenso. */
    mean: number | null;
    /** Divisa declarada por Yahoo para el listado; null si no la declara. */
    currency: string | null;
    /** Firmas con objetivo en los últimos 12 meses. */
    firms: number;
    fetchedAt: number | null;
    source: string;
    note: string | null;
};

interface BackendAnalystTargets {
    status?: 'available' | 'empty' | 'unavailable';
    source?: string;
    fetched_at?: number;
    currency?: string | null;
    consensus?: { mean?: number | null } | null;
    rows?: unknown[];
    note?: string | null;
}

/**
 * `quoteSymbol` opcional: la página que ya resolvió el listado real
 * (watchlist) lo pasa y evita otra llamada de basics. `null` explícito =
 * sin listado verificado: no se consulta nada (un ticker desnudo puede
 * resolver a otro emisor). Omitido = se resuelve aquí (cartera).
 */
export async function getListingAnalystTargets(
    ticker: string,
    quoteSymbol?: string | null,
): Promise<ListingAnalystTargets | null> {
    const normalized = ticker.trim().toUpperCase();
    if (!normalized) return null;
    let listing: string | null;
    if (quoteSymbol === undefined) {
        const basics = await getResearchCompanyBasics(normalized);
        listing = quoteSymbolFor(basics, normalized);
    } else {
        listing = quoteSymbol;
    }
    if (!listing) return null;
    try {
        const data = await researchRequest<BackendAnalystTargets>(
            `/api/companies/${encodeURIComponent(listing)}/analyst-targets`,
            { timeoutMs: 14000 },
        );
        const mean = typeof data.consensus?.mean === 'number' && Number.isFinite(data.consensus.mean) && data.consensus.mean > 0
            ? data.consensus.mean
            : null;
        return {
            status: data.status ?? 'unavailable',
            mean,
            currency: typeof data.currency === 'string' && data.currency.trim() !== '' ? data.currency.trim().toUpperCase() : null,
            firms: Array.isArray(data.rows) ? data.rows.length : 0,
            fetchedAt: typeof data.fetched_at === 'number' ? data.fetched_at : null,
            source: data.source ?? 'Yahoo Finance (no oficial), agregado de analistas',
            note: data.note ?? null,
        };
    } catch {
        return null;
    }
}
