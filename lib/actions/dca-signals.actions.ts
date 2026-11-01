'use server';

import { requestLocale } from '@/lib/research/backend-error-locale';
import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { AppError, classifyError, getFriendlyErrorMessage, type ErrorCause } from '@/lib/types/errors';
import type { DcaBacktest, DcaEvaluateSummary, DcaHitRates, DcaSignalsResponse } from '@/lib/dca/types';

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

export async function startDcaManualJob(): Promise<DcaMutationResult & { runId?: number }> {
    try {
        await requireAuthenticatedUser();
        const receipt = await researchRequest<{ run_id: number }>('/api/watchlist/dca-signals/evaluate-async', { method: 'POST' });
        return { success: true, runId: receipt.run_id };
    } catch (error) {
        return { success: false, code: classifyError(error), message: getFriendlyErrorMessage(error, { locale: await requestLocale() }) };
    }
}

export async function getDcaManualJob(runId: number): Promise<DcaMutationResult & { status?: string; summary?: DcaEvaluateSummary }> {
    try {
        await requireAuthenticatedUser();
        if (!Number.isSafeInteger(runId) || runId < 1) throw new Error('Ejecución no válida');
        const result = await researchRequest<{ status: string; summary: DcaEvaluateSummary | null; error: string | null }>(`/api/watchlist/dca-signals/manual-runs/${runId}`);
        if (result.status === 'ok') revalidatePath('/watchlist');
        return { success: true, status: result.status, summary: result.summary ?? undefined,
            message: result.status === 'error' ? 'La evaluación falló. Revisa el estado en la watchlist.' : undefined };
    } catch (error) {
        return { success: false, code: classifyError(error), message: getFriendlyErrorMessage(error, { locale: await requestLocale() }) };
    }
}

export type DcaHitRatesState =
    | { status: 'ok'; data: DcaHitRates }
    | { status: 'not_evaluated' }
    | { status: 'unavailable' };

/** Como `getDcaHitRates` pero distingue «el backend dice que no hay señal
    evaluada» (404) de «no se pudo consultar» (error, timeout, sin sesión). */
export async function getDcaHitRatesState(symbol: string): Promise<DcaHitRatesState> {
    try {
        await requireAuthenticatedUser();
        const data = await researchRequest<DcaHitRates>(`/api/watchlist/dca-signals/${encodeURIComponent(symbol)}/hit-rates`);
        return data ? { status: 'ok', data } : { status: 'unavailable' };
    } catch (error) {
        // Solo el 404 ESPECÍFICO del backend cuenta como «sin señal evaluada»; un
        // 404 genérico (deploy, proxy, ruta) es «no disponible».
        if (error instanceof AppError && error.statusCode === 404 && /sin señal DCA evaluada/i.test(error.message)) {
            return { status: 'not_evaluated' };
        }
        console.error('getDcaHitRates error:', error);
        return { status: 'unavailable' };
    }
}

/** «¿Cuántas veces estaba más arriba?» de un ticker seguido (histórico de la
    última evaluación). null = servicio caído o ticker sin señal evaluada. */
export async function getDcaHitRates(symbol: string): Promise<DcaHitRates | null> {
    const state = await getDcaHitRatesState(symbol);
    return state.status === 'ok' ? state.data : null;
}

/** Backtest DCA plano vs DCA por niveles (Fórmula Nico v1) de cualquier ticker.
    Sin look-ahead: el backend usa solo datos hasta el cierre de cada mes. */
export async function getDcaBacktest(input: {
    symbol: string;
    start?: string;
    end?: string;
    base?: number;
}): Promise<{ data: DcaBacktest | null; error: string | null }> {
    const symbol = input.symbol.trim().toUpperCase();
    if (!/^[A-Z0-9.\-=^]{1,24}$/.test(symbol)) {
        return { data: null, error: 'Ticker no válido' };
    }
    const params = new URLSearchParams();
    if (input.start) params.set('start', input.start);
    if (input.end) params.set('end', input.end);
    if (input.base && Number.isFinite(input.base) && input.base > 0) params.set('base', String(input.base));
    try {
        await requireAuthenticatedUser();
        const query = params.toString();
        const data = await researchRequest<DcaBacktest>(
            `/api/watchlist/dca-signals/${encodeURIComponent(symbol)}/backtest${query ? `?${query}` : ''}`,
        );
        return { data, error: null };
    } catch (error) {
        console.error('getDcaBacktest error:', error);
        return { data: null, error: getFriendlyErrorMessage(error, { locale: await requestLocale() }) };
    }
}
