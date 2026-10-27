'use server';

import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest, jsonBody } from '@/lib/research/client';
import { classifyError, getFriendlyErrorMessage, type ErrorCause } from '@/lib/types/errors';
import type { DcaEvaluateSummary, DcaHitRates, DcaSignalsResponse } from '@/lib/dca/types';

/** Señales DCA (watchlist + cartera) del backend research. `unavailable`
    distingue un fallo del servicio de una lista realmente vacía. */
export async function getDcaSignals(): Promise<{ data: DcaSignalsResponse | null; unavailable: boolean }> {
    try {
        await requireAuthenticatedUser();
        const data = await researchRequest<DcaSignalsResponse>('/api/watchlist/dca-signals');
        if (!data || !Array.isArray(data.items)) return { data: null, unavailable: true };
        return { data, unavailable: false };
    } catch (error) {
        console.error('getDcaSignals error:', error);
        return { data: null, unavailable: true };
    }
}

export interface DcaMutationResult {
    success: boolean;
    code?: ErrorCause;
    message?: string;
}

/** Nivel mínimo de aviso por ticker: null = global, 0 = sin avisos, 1-4. */
export async function setDcaAlertMinLevel(symbol: string, minLevel: number | null): Promise<DcaMutationResult> {
    try {
        await requireAuthenticatedUser();
        await researchRequest(`/api/watchlist/${encodeURIComponent(symbol)}/dca-alert-min-level`, {
            method: 'PUT',
            body: jsonBody({ min_level: minLevel }),
        });
        revalidatePath('/watchlist');
        return { success: true };
    } catch (error) {
        console.error('setDcaAlertMinLevel error:', error);
        return { success: false, code: classifyError(error), message: getFriendlyErrorMessage(error) };
    }
}

/** Evaluación manual (el backend la limita a una por minuto). */
export async function evaluateDcaSignalsNow(): Promise<DcaMutationResult & { summary?: DcaEvaluateSummary }> {
    try {
        await requireAuthenticatedUser();
        const summary = await researchRequest<DcaEvaluateSummary>('/api/watchlist/dca-signals/evaluate', {
            method: 'POST',
        });
        revalidatePath('/watchlist');
        return { success: true, summary };
    } catch (error) {
        console.error('evaluateDcaSignalsNow error:', error);
        return { success: false, code: classifyError(error), message: getFriendlyErrorMessage(error) };
    }
}

/** «¿Cuántas veces estaba más arriba?» de un ticker seguido (histórico de la
    última evaluación). null = servicio caído o ticker sin señal evaluada. */
export async function getDcaHitRates(symbol: string): Promise<DcaHitRates | null> {
    try {
        await requireAuthenticatedUser();
        return await researchRequest<DcaHitRates>(`/api/watchlist/dca-signals/${encodeURIComponent(symbol)}/hit-rates`);
    } catch (error) {
        console.error('getDcaHitRates error:', error);
        return null;
    }
}
