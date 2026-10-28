'use server';

import type { BrainPageContext } from '@/lib/brain/page-context';
import type { LibraryAnalysis } from '@/lib/knowledge/analysis';
import { jsonBody, researchRequest } from '@/lib/research/client';

export type LibraryAnswer = {
  status: 'ok' | 'fragmentos' | 'sin_datos';
  kind: 'doctrina';
  mode?: 'respuesta' | 'analisis';
  analysis?: LibraryAnalysis;
  retrieval: string;
  message: string | null;
  answers: {
    text: string | null;
    citation: {
      chunk_id: number; document_id: number; title: string; author: string | null;
      page_number: number | null; chunk_index: number; quote: string;
      source_url: string | null; publication_date: string | null; document_type: string;
    };
  }[];
};

export async function askKnowledge(question: string, scope: 'letters' | 'library', author?: string, mode: 'respuesta' | 'analisis' = 'respuesta', page?: BrainPageContext | null, documentId?: number): Promise<LibraryAnswer> {
  const trimmed = question.trim();
  if (trimmed.length < 3 || trimmed.length > 1200) throw new Error('Escribe una pregunta de 3 a 1200 caracteres.');
  // POST LLM: presupuesto explícito, no el GET rápido. Sin catch: conserva errores API/sesión.
  return researchRequest<LibraryAnswer>('/api/knowledge/chat', {
    method: 'POST', timeoutMs: mode === 'analisis' ? 90_000 : 60_000,
    body: jsonBody({ question: trimmed, scope, author: author || null, mode, page: page ?? null, ...(Number.isSafeInteger(documentId) && documentId! > 0 ? { document_id: documentId } : {}) }),
  });
}
