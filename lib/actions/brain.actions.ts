'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import type { BrainPageContext } from '@/lib/brain/page-context';
import { toPortfolioChatCitations } from '@/lib/chat/citations';
import { jsonBody, researchRequest } from '@/lib/research/client';
import { AuthorizationError, ExternalAPIError, ValidationError } from '@/lib/types/errors';

type ResearchChatResponse = {
    answer: string;
    blocked: boolean;
    proposed_actions: string[];
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
export type BrainHistoryTurn = { role: 'user' | 'assistant'; content: string };

/** Últimos turnos que viajan con la pregunta: acotados, solo texto. */
function trimBrainHistory(history?: BrainHistoryTurn[] | null): BrainHistoryTurn[] {
    return (history ?? [])
        .filter((turn) => (turn.role === 'user' || turn.role === 'assistant') && turn.content.trim())
        .slice(-6)
        .map((turn) => ({ role: turn.role, content: turn.content.slice(0, 1500) }));
}

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
            body: jsonBody({ question, scope: 'portfolio', ticker: null, page: page ?? null, history: trimBrainHistory(history) }),
        });
    } catch (error) {
        // Return known transport errors as data: Next hides server exception
        // details in production, so the browser cannot classify a timeout.
        if (!(error instanceof ExternalAPIError)) throw error;
        const timedOut = error.originalError instanceof DOMException
            && error.originalError.name === 'TimeoutError';
        return {
            success: false,
            message: timedOut
                ? 'La respuesta tarda más de lo normal. Reinténtalo en unos segundos.'
                : 'El asistente no está disponible ahora. Reinténtalo en unos segundos.',
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
        context: response.context ?? null,
    };
}
