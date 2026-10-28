'use server';

import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest, jsonBody } from '@/lib/research/client';

export type DcaAlertSettings = {
    configured: boolean;
    up_min_level: number;
    down_max_level: number;
    legacy_override_count: number;
    legacy_min_level: number;
    alerts_enabled: boolean;
    trims_enabled: boolean;
};

export async function getDcaAlertSettings(): Promise<DcaAlertSettings> {
    await requireAuthenticatedUser();
    return researchRequest<DcaAlertSettings>('/api/settings/dca', { cache: 'no-store' });
}

export async function saveDcaAlertSettings(upMinLevel: number, downMaxLevel: number): Promise<DcaAlertSettings> {
    await requireAuthenticatedUser();
    if (![upMinLevel, downMaxLevel].every((v) => Number.isInteger(v) && v >= 0 && v <= 4)) {
        throw new Error('Nivel DCA no válido');
    }
    const result = await researchRequest<DcaAlertSettings>('/api/settings/dca', {
        method: 'PUT', body: jsonBody({ up_min_level: upMinLevel, down_max_level: downMaxLevel }),
    });
    revalidatePath('/settings');
    revalidatePath('/watchlist');
    return result;
}
