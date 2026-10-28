'use server';

import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { requestCache } from '@/lib/cache/requestCache';

/** Divisa base de la cartera (por tenant) y procedencia de los tipos de cambio. */
export type PortfolioCurrencySettings = {
    base_currency: string;
    /** IRPF y Modelo 720: siempre EUR al tipo BCE, sea cual sea la base. */
    tax_currency?: string;
    fx_source?: { source: string | null; latest_rate_date: string | null; base_currency: string } | null;
};

/** GET /api/portfolio/configuration. */
export async function getPortfolioCurrencySettings(): Promise<PortfolioCurrencySettings> {
    await requireAuthenticatedUser();
    return researchRequest<PortfolioCurrencySettings>('/api/portfolio/configuration', { cache: 'no-store' });
}

/** Claves de caché de cartera (lib/actions/portfolio.actions.ts) cuyos importes van en la divisa base. */
const PORTFOLIO_READS_IN_BASE_CURRENCY = ['positions', 'summary', 'transactions', 'snapshots', 'tearsheet', 'dividends', 'scores', 'quality'] as const;

/** PUT /api/portfolio/configuration: cambia la base y revalora la cartera (no reescribe operaciones). */
export async function savePortfolioBaseCurrency(baseCurrency: string): Promise<PortfolioCurrencySettings> {
    const user = await requireAuthenticatedUser();
    const result = await researchRequest<PortfolioCurrencySettings>('/api/portfolio/configuration', {
        method: 'PUT',
        body: JSON.stringify({ base_currency: baseCurrency }),
    });
    // Suite E2E de flujos (28-oct-2026): revalidatePath no toca la caché en
    // memoria de las lecturas de cartera (TTL 15 s). Tras «Divisa base: USD.
    // Cartera revalorada.», /portfolio seguía pintando los totales en EUR,
    // con el símbolo €, hasta que caducaba. Toda lectura valorada en la base
    // queda obsoleta con el cambio.
    for (const suffix of PORTFOLIO_READS_IN_BASE_CURRENCY) {
        requestCache.invalidate(`portfolio:${user.id}:${suffix}`);
    }
    revalidatePath('/portfolio');
    revalidatePath('/settings');
    return result;
}
