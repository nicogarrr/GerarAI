import 'server-only';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { trimBrainHistory } from '@/lib/brain/history';
import { jsonBody, researchRequest } from '@/lib/research/client';
import type { AssistantRequest, AssistantResponse, GuideContext } from '@/lib/research/assistant-contract';

/** Solo el endpoint nuevo: /api/chat antiguo puede escribir en memoria. */
export async function askResearchAssistant(request: AssistantRequest): Promise<AssistantResponse> {
  await requireAuthenticatedUser();
  const question = request.question.trim();
  const ticker = request.ticker?.trim().toUpperCase();
  if (question.length < 3 || question.length > 2000) throw new Error('La pregunta debe tener entre 3 y 2000 caracteres.');
  if (request.mode !== 'explore' && request.mode !== 'guide') throw new Error('Modo de investigación no válido.');
  if (request.mode === 'guide' && !ticker) throw new Error('La guía necesita un ticker.');
  if (request.review_id !== undefined && (!Number.isSafeInteger(request.review_id) || request.review_id < 1 || request.mode !== 'guide')) {
    throw new Error('Revisión no válida.');
  }
  const response = await researchRequest<AssistantResponse>('/api/research/assistant', {
    method: 'POST',
    body: jsonBody({ mode: request.mode, question, ...(ticker ? { ticker } : {}), ...(request.review_id ? { review_id: request.review_id } : {}), ...(request.page ? { page: request.page } : {}), history: trimBrainHistory(request.history) }),
  });
  // Fallo cerrado: un backend incompatible no puede presentarse como modo sin escritura.
  if (response.writeback !== false || response.mode !== request.mode ||
      (response.status !== 'answered' && response.status !== 'insufficient_data') ||
      !Array.isArray(response.sections) || !Array.isArray(response.citations) ||
      !Array.isArray(response.missing_data) || !Array.isArray(response.suggested_next_steps)) {
    throw new Error('Respuesta del asistente incompatible con el contrato de solo lectura.');
  }
  return response;
}

export async function getGuideContext(ticker: string): Promise<GuideContext> {
  await requireAuthenticatedUser();
  const value = ticker.trim().toUpperCase();
  if (!value) throw new Error('Ticker obligatorio.');
  return researchRequest<GuideContext>(`/api/research/guide-context?ticker=${encodeURIComponent(value)}`);
}
