'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { sanitizeDebate, type SanitizedDebate } from '@/lib/research/debate-sanitize';
import { debateErrorMessage } from '@/lib/research/debate-error';
import { requestLocale } from '@/lib/research/backend-error-locale';
import { createTranslator } from '@/lib/i18n/translate';
import { assertPositiveInt } from '@/lib/validation/pathParams';
import type { components } from '@/lib/research/openapi.generated';

export type ThesisJobPhase = components['schemas']['ThesisJobPhaseOut'];

/** Alias del contrato generado; `result` conserva la vista estrecha medida del
 *  front (el worker escribe thesis_version_id/version/status) porque el payload
 *  completo es libre en el backend. */
export type ThesisJobStatus = Omit<components['schemas']['ThesisJobStatusOut'], 'result'> & {
    result?: { thesis_version_id?: number; version?: number; status?: string } | null;
};

/** POST /api/thesis/generate-async — encola generación en segundo plano (202).
 *  `requestId` identifica el click del usuario: sin él el backend replaya el
 *  último run exitoso y nunca se regeneraría. */
export async function startThesisJob(
    ticker: string,
    force = true,
    requestId?: string,
): Promise<ThesisJobStatus> {
    await requireAuthenticatedUser();
    return researchRequest<ThesisJobStatus>('/api/thesis/generate-async', {
        method: 'POST',
        body: JSON.stringify({
            ticker: ticker.toUpperCase(),
            force_new_version: force,
            ...(requestId ? { request_id: requestId } : {}),
        }),
    });
}

/** GET /api/thesis/jobs/{id} — estado real del job (fases reales, sin ETAs). */
export async function getThesisJobStatus(runId: number): Promise<ThesisJobStatus> {
    await requireAuthenticatedUser();
    return researchRequest<ThesisJobStatus>(`/api/thesis/jobs/${assertPositiveInt(runId, 'runId')}`);
}

/** Server is the source of truth; recovery works across tabs and devices. */
export async function getLatestThesisJob(ticker: string): Promise<ThesisJobStatus | null> {
    await requireAuthenticatedUser();
    const clean = ticker.trim().toUpperCase();
    if (!/^[A-Z0-9.\-]{1,20}$/.test(clean)) throw new Error('Ticker no válido');
    const response = await researchRequest<{ job: ThesisJobStatus | null }>(
        `/api/thesis/jobs?ticker=${encodeURIComponent(clean)}`,
    );
    return response.job;
}

export type ThesisDebateResult = SanitizedDebate;

export type ThesisDebateOutcome =
    | { ok: true; debate: ThesisDebateResult }
    | { ok: false; error: string };

/**
 * El debate encadena 2 llamadas LLM (~35 s): el timeout global de 15 s lo cortaba.
 * La ruta research/[ticker] tiene maxDuration = 60 s en Vercel, asi que el
 * timeout propio debe quedar por debajo para que se active nuestro mensaje.
 * Si un debate supera ~55 s la accion devuelve el error de timeout controlado.
 */
const DEBATE_TIMEOUT_MS = 55_000;

/**
 * POST /api/thesis/{ticker}/debate — debate bull/bear (503 si no hay LLM gratuito disponible).
 * Devuelve un resultado tipado en lugar de lanzar: un throw en una server action
 * llega a produccion como el error React #441 sin mensaje. La salida del LLM se
 * sanea y valida antes de salir del servidor.
 */
export async function runThesisDebate(ticker: string): Promise<ThesisDebateOutcome> {
    await requireAuthenticatedUser();
    const clean = ticker.trim().toUpperCase();
    if (!/^[A-Z0-9.\-]{1,20}$/.test(clean)) return { ok: false, error: 'Ticker no válido' };
    try {
        const raw = await researchRequest<unknown>(`/api/thesis/${encodeURIComponent(clean)}/debate`, {
            method: 'POST',
            timeoutMs: DEBATE_TIMEOUT_MS,
        });
        const debate = sanitizeDebate(raw);
        if (!debate) return { ok: false, error: createTranslator(await requestLocale())('research.debateErrors.discarded') };
        return { ok: true, debate };
    } catch (exc) {
        return { ok: false, error: debateErrorMessage(exc, await requestLocale()) };
    }
}

export interface ThesisApproval {
    ticker: string;
    thesis_version_id: number;
    version: number;
    status: string;
    decision: 'approved' | 'rejected';
    actor: string;
    approved_at: string;
    telegram_auto_approval: string;
    /** Resultado real del indexado en la Biblioteca (RAG) tras la decision.
     *  null en backends antiguos; la UI solo afirma lo que llega. */
    knowledge_sync?: { status: 'indexed' | 'unchanged' | 'removed' | 'none' | 'failed'; document_id: number | null } | null;
}

/**
 * POST /api/thesis/{ticker}/approve — aprobacion manual de la ultima tesis.
 * La aprobacion automatica por Telegram queda como futura (el endpoint lo
 * declara en `telegram_auto_approval: "future"`).
 */
export async function approveThesis(
    ticker: string,
    decision: 'approved' | 'rejected',
    actor = 'user',
): Promise<ThesisApproval> {
    await requireAuthenticatedUser();
    const clean = ticker.trim().toUpperCase();
    if (!/^[A-Z0-9.\-]{1,20}$/.test(clean)) throw new Error('Ticker no válido');
    if (decision !== 'approved' && decision !== 'rejected') throw new Error('Decisión no válida');
    return researchRequest<ThesisApproval>(`/api/thesis/${encodeURIComponent(clean)}/approve`, {
        method: 'POST',
        body: JSON.stringify({ decision, actor: actor.slice(0, 160) || 'user' }),
    });
}
