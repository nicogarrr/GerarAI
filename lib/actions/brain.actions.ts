'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { trimBrainHistory, type BrainHistoryTurn } from '@/lib/brain/history';
import type { BrainPageContext } from '@/lib/brain/page-context';
import { toPortfolioChatCitations } from '@/lib/chat/citations';
import { expertTeamFromResponse, expertTeamTimeoutsFromResponse } from '@/lib/chat/expert-team';
import { requestLocale } from '@/lib/research/backend-error-locale';
import { jsonBody, researchRequest } from '@/lib/research/client';
import { AppError, AuthorizationError, ExternalAPIError, ValidationError } from '@/lib/types/errors';

type ResearchChatResponse = {
    answer: string;
    blocked: boolean;
    proposed_actions: string[];
    model?: string | null;
    llm_trace?: unknown;
    context?: {
        path: string;
        label: string;
        ticker: string | null;
        company_name: string | null;
        company_resolved: boolean;
    } | null;
    sources: Array<{
        type: string;
        id: number | string | null;
        title: string;
        document_id?: number | null;
        page_number?: number | null;
        chunk_index?: number | null;
        source_type?: string | null;
        [key: string]: unknown;
    }>;
};

/**
 * Cerebro global de GerarAI (SOLO LECTURA): una sola acción para el chat
 * montado en el layout. El contexto de página ("Viendo X") viaja como texto
 * y se resuelve en servidor; la respuesta lo devuelve ya resuelto para la
 * pastilla. Las rutas degradadas hablan castellano.
 */
export async function chatWithPortfolio(
    query: string,
    userId: string,
    page?: BrainPageContext | null,
    history?: BrainHistoryTurn[] | null,
) {
    const user = await requireAuthenticatedUser();
    if (userId !== user.id) {
        throw new AuthorizationError('Cannot access another user portfolio');
    }
    const question = query.trim();
    if (question.length < 3) {
        throw new ValidationError('Escribe una pregunta de al menos 3 caracteres', 'query');
    }
    let response: ResearchChatResponse;
    try {
        response = await researchRequest<ResearchChatResponse>('/api/chat', {
            method: 'POST',
            // Idioma de Ajustes → Idioma: las respuestas fijas del chat (posición,
            // coste medio, peso, rentabilidad) salen en ese idioma cuando el motor
            // tiene activa la generación multidioma; si no, en español como siempre.
            headers: { 'x-gerarai-language': await requestLocale() },
            body: jsonBody({ question, scope: 'portfolio', ticker: null, page: page ?? null, history: trimBrainHistory(history) }),
        });
    } catch (error) {
        // Return known transport errors as data: Next hides server exception
        // details in production, so the browser cannot classify a timeout.
        // Clasificar solo estados HTTP conocidos, nunca devolver el detalle
        // del backend: puede incluir diagnósticos internos. Auth y validación
        // siguen propagándose y no se presentan como falta de datos.
        const httpMessage = error instanceof AppError && error.code === 'RESEARCH_API_ERROR'
            ? error.statusCode === 429
                ? 'Hay demasiadas consultas ahora. Reinténtalo más tarde.'
                : error.statusCode === 504
                    ? 'La respuesta tarda más de lo normal. Reinténtalo más tarde.'
                    : error.statusCode === 502 || error.statusCode === 503
                        ? 'El asistente no está disponible ahora. Reinténtalo más tarde.'
                        : null
            : null;
        if (!httpMessage && !(error instanceof ExternalAPIError)) throw error;
        const timedOut = error instanceof ExternalAPIError
            && error.originalError instanceof DOMException
            && error.originalError.name === 'TimeoutError';
        return {
            success: false,
            message: httpMessage ?? (timedOut
                ? 'La respuesta tarda más de lo normal. Reinténtalo en unos segundos.'
                : 'El asistente no está disponible ahora. Reinténtalo en unos segundos.'),
            proposedActions: [],
            citations: [],
            context: null,
        };
    }
    return {
        success: !response.blocked,
        message: response.answer,
        proposedActions: response.proposed_actions,
        citations: toPortfolioChatCitations(response.sources),
        // Equipo de expertos (flag del motor, apagado por defecto): quién respondió.
        experts: expertTeamFromResponse(response),
        expertsTimedOut: expertTeamTimeoutsFromResponse(response),
        context: response.context ?? null,
    };
}
