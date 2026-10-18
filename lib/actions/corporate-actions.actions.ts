'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type CorporateActionRecord = Record<string, unknown>;

/** GET /api/corporate-actions — lista de acciones corporativas pendientes/aplicables */
export async function getCorporateActions(): Promise<CorporateActionRecord[]> {
    await requireAuthenticatedUser();
    return researchRequest<CorporateActionRecord[]>('/api/corporate-actions');
}

/** POST /api/corporate-actions/{action_id}/apply — aplica una acción corporativa a la cartera */
export async function applyCorporateAction(actionId: number): Promise<CorporateActionRecord> {
    await requireAuthenticatedUser();
    if (!Number.isFinite(actionId)) {
        throw new Error('Identificador de acción corporativa inválido');
    }
    return researchRequest<CorporateActionRecord>(`/api/corporate-actions/${actionId}/apply`, {
        method: 'POST',
    });
}
export type CorporateActionsSyncStatus = {
    dividends_last_import: string | null;
    splits_last_import: string | null;
};

/** GET /api/corporate-actions/sync-status — última importación real por fuente. */
export async function getCorporateActionsSyncStatus(): Promise<CorporateActionsSyncStatus | null> {
    await requireAuthenticatedUser();
    try {
        return await researchRequest<CorporateActionsSyncStatus>('/api/corporate-actions/sync-status');
    } catch {
        return null;
    }
}
