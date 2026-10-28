'use server';

import { researchRequest } from '@/lib/research/client';
import { AppError } from '@/lib/types/errors';

export interface PaperTradeView {
    id: number; ticker: string; direction: 'long' | 'short'; horizon: 'short' | 'five_years';
    thesis: string; conviction: string; proposed_entry: string; stop: string; target: string;
    quantity?: string; price_source?: string | null; inference_basis: string; status: string; currency: string | null; created_at: string;
    entry_price: string | null; exit_price: string | null; mark_price: string | null;
    mark_at: string | null; entry_at: string | null; exit_at: string | null;
    realized_pnl: string | null; unrealized_pnl: string | null; close_reason: string | null;
    realized_pnl_net?: string | null; unrealized_pnl_net?: string | null;
    entry_fee?: string | null; exit_fee?: string | null;
    cost_label?: string | null; cost_assumption_version?: string | null;
    dividends_total?: string | null; dividends_count?: number | null;
    dividends_uncertain?: number | null; dividends_wrong_currency?: number | null;
    dividends_source?: string | null;
    split_adjustments?: number | null; last_corporate_action?: string | null;
    corporate_action_warning?: string | null;
    /** Tesis vigente del tenant al crear la propuesta (null = no había). */
    thesis_version_id?: number | null;
    thesis_anchor?: PaperThesisAnchor | null;
}
/** Versión de tesis anclada y si existe una más nueva para la misma empresa. */
export interface PaperThesisAnchor {
    id: number; version: number; created_at: string | null; latest_version: number; superseded: boolean;
}
export interface PaperCalibration {
    base: string; calculado_en: string; propuestas_llm: number; cerradas_con_resultado: number;
    muestra_insuficiente: boolean; minimo_cerradas: number; aviso: string | null;
    brier: number | null; brier_referencia_sin_informacion: number | null;
    bins: Array<{ rango: string; cerradas: number; conviction_media: number | null;
        tasa_acierto: number | null; hueco: number | null; aviso: string | null }>;
}
export interface PaperScore {
    calibracion?: PaperCalibration;
    groups: Array<{ horizon: string; currency: string; proposals: number; closed: number;
        open: number; wins: number; losses: number; flat: number; hit_rate: number | null;
        realized_pnl: string | null; unrealized_pnl: string | null; missing_marks: number;
        closed_net?: number; hit_rate_net?: number | null; realized_pnl_net?: string | null;
        closed_distorted?: number }>;
}
export type PaperState = { trades: PaperTradeView[]; score: PaperScore; error?: string };

export type PaperFeedResult = { success: true } | { success: false; message: string };

/** Encola un lote de propuestas simuladas del modelo (202; cuota diaria compartida). */
export async function feedPaperProposalsNow(): Promise<PaperFeedResult> {
    try {
        await researchRequest('/api/paper-trading/feed', { method: 'POST' });
        return { success: true };
    } catch (error) {
        console.error('feedPaperProposalsNow error:', error);
        return { success: false, message: error instanceof AppError ? error.message : 'No se pudo encolar la generación.' };
    }
}

export async function getPaperTrading(): Promise<PaperState> {
    try {
        const [trades, score] = await Promise.all([
            researchRequest<PaperTradeView[]>('/api/paper-trading/proposals'),
            researchRequest<PaperScore>('/api/paper-trading/scoreboard'),
        ]);
        return { trades, score };
    } catch (error) {
        if (error instanceof AppError && ['EXTERNAL_API_ERROR', 'RESEARCH_API_ERROR'].includes(error.code) && ![401, 403].includes(error.statusCode ?? 0)) {
            return { trades: [], score: { groups: [] }, error: 'No se pudo cargar la cartera simulada.' };
        }
        throw error;
    }
}
