'use server';

import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

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

/** PUT /api/portfolio/configuration: cambia la base y revalora la cartera (no reescribe operaciones). */
export async function savePortfolioBaseCurrency(baseCurrency: string): Promise<PortfolioCurrencySettings> {
    await requireAuthenticatedUser();
    const result = await researchRequest<PortfolioCurrencySettings>('/api/portfolio/configuration', {
        method: 'PUT',
        body: JSON.stringify({ base_currency: baseCurrency }),
    });
    revalidatePath('/portfolio');
    revalidatePath('/settings');
    return result;
}
