'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type RiskDashboardRecord = Record<string, unknown>;

/** GET /api/risk/dashboard — métricas agregadas de riesgo de la cartera */
export async function getRiskDashboard(): Promise<RiskDashboardRecord> {
    await requireAuthenticatedUser();
    return researchRequest<RiskDashboardRecord>('/api/risk/dashboard');
}