'use server';

import { revalidatePath } from 'next/cache';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type PlanRecord = Record<string, unknown>;

/** El backend responde {"plan_exists": false} cuando no hay plan: se
 *  normaliza a null para que la UI muestre su estado vacío honesto en
 *  lugar de pintar el stub crudo ("PLAN_EXISTS No"). */
function nullIfPlanStub(record: PlanRecord | null): PlanRecord | null {
    if (record && record.plan_exists === false) return null;
    return record;
}

/** GET /api/plan — plan de inversión a largo plazo */
export async function getPlan(): Promise<PlanRecord | null> {
    await requireAuthenticatedUser();
    return nullIfPlanStub(await researchRequest<PlanRecord>('/api/plan'));
}

/** GET /api/plan/contributions — historial de aportaciones */
export async function getPlanContributions(): Promise<PlanRecord[]> {
    await requireAuthenticatedUser();
    return researchRequest<PlanRecord[]>('/api/plan/contributions');
}

/** GET /api/plan/drift — análisis de desviación respecto al objetivo */
export async function getPlanDrift(): Promise<PlanRecord | null> {
    await requireAuthenticatedUser();
    return nullIfPlanStub(await researchRequest<PlanRecord>('/api/plan/drift'));
}
export type PlanTargetInput = {
    kind: 'ticker' | 'sector' | 'asset_class';
    label: string;
    target_pct: number;
    band_pct: number;
};

export type PlanUpsertPayload = {
    monthly_contribution: number;
    /** Solo con la capability currency_contract_enabled; omitirlo conserva la divisa registrada. */
    monthly_contribution_currency?: string;
    start_date: string;
    horizon_years: number;
    target_allocations: PlanTargetInput[];
};

/** PUT /api/plan — crea o actualiza el plan de inversión (B12: antes no
 *  existía ninguna vía de alta desde la UI). */
export async function upsertPlan(payload: PlanUpsertPayload): Promise<void> {
    await requireAuthenticatedUser();
    await researchRequest('/api/plan', {
        method: 'PUT',
        body: JSON.stringify(payload),
    });
    revalidatePath('/plan');
}
