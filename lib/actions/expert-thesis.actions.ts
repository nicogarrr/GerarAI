'use server';

import { researchRequest } from '@/lib/research/client';
import type { components } from '@/lib/research/openapi.generated';

export type ExpertThesis = components['schemas']['ExpertThesisOut'];

/**
 * Última tesis guardada del equipo de expertos para un ticker. El backend
 * responde 404 con EXPERT_TEAM_ENABLED apagado y null si no hay ninguna: en
 * ambos casos, y ante cualquier fallo, la pantalla simplemente no la muestra
 * (es una capa opcional; nunca rompe la tesis de siempre).
 */
export async function getExpertThesis(ticker: string): Promise<ExpertThesis | null> {
    const encoded = encodeURIComponent(ticker.trim().toUpperCase());
    if (!encoded) return null;
    try {
        const data = await researchRequest<ExpertThesis | null>(`/api/thesis/${encoded}/experts`, { cache: 'no-store' });
        return data && Array.isArray(data.sections) ? data : null;
    } catch {
        return null;
    }
}
