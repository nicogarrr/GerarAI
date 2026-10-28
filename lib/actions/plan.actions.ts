'use server';

import { revalidatePath } from 'next/cache';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { isContributionSplit, type ContributionSplit } from '@/lib/plan/contribution-split';

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

/** GET /api/plan/contribution-split — reparto de la aportación de este mes
 *  ponderado por nivel DCA. Opcional: si el backend aún no lo expone o falla,
 *  devuelve null y la tarjeta muestra su estado vacío (no rompe /plan). */
export async function getPlanContributionSplit(): Promise<ContributionSplit | null> {
    await requireAuthenticatedUser();
    try {
        const record = await researchRequest<unknown>('/api/plan/contribution-split');
        return isContributionSplit(record) ? record : null;
    } catch {
        return null;
    }
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
/** Rechazos 409 del contrato de divisa: se devuelven como resultado (un Server
 *  Action en produccion oculta el mensaje de las excepciones). */
export type PlanUpsertResult =
    | { ok: true }
    | { ok: false; code: 'plan_currency_required_for_amount_change' | 'plan_currency_contract_disabled' };

const PLAN_CURRENCY_REJECTIONS = ['plan_currency_required_for_amount_change', 'plan_currency_contract_disabled'] as const;

export async function upsertPlan(payload: PlanUpsertPayload): Promise<PlanUpsertResult> {
    await requireAuthenticatedUser();
    try {
        await researchRequest('/api/plan', {
            method: 'PUT',
            body: JSON.stringify(payload),
        });
    } catch (error) {
        const message = error instanceof Error ? error.message : '';
        const code = PLAN_CURRENCY_REJECTIONS.find((c) => message.includes(c));
        if (code) return { ok: false, code };
        throw error;
    }
    revalidatePath('/plan');
    revalidatePath('/portfolio');
    return { ok: true };
}

/** Read-only savings preview; it never changes the plan or places an order. */
export async function getSavingsProjection(input?: import('@/lib/plan/savings-projection').SavingsPreviewInput): Promise<import('@/lib/plan/savings-projection').SavingsProjection> {
    await requireAuthenticatedUser();
    const query = input ? new URLSearchParams({ monthly: String(input.monthly), years: String(input.years), currency: input.currency, dividend_yield: String(input.dividendYield), inflation: String(input.inflation) }) : null;
    return researchRequest(`/api/plan/savings-projection${query ? `?${query}` : ''}`);
}
