import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest } = vi.hoisted(() => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));

import { AppError } from '@/lib/types/errors';
import { askKnowledgeResult } from '@/lib/actions/knowledge-chat.actions';

beforeEach(() => vi.clearAllMocks());

describe('askKnowledgeResult', () => {
    it('una pregunta fuera de 3..1200 vuelve como validacion con su mensaje, no como throw', async () => {
        // En prod Next enmascaraba el throw y el panel decia «No se pudo
        // consultar la biblioteca» para una pregunta de 2 caracteres.
        await expect(askKnowledgeResult('ok', 'library')).resolves.toEqual({
            ok: false,
            cause: 'validation',
            message: 'Escribe una pregunta de 3 a 1200 caracteres.',
        });
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('respuesta del motor envuelta como { ok: true, answer }', async () => {
        const answer = { status: 'sin_datos', retrieval: 'solo_texto', message: 'Sin datos', answers: [] };
        researchRequest.mockResolvedValue(answer);
        await expect(askKnowledgeResult('¿Qué dice Buffett?', 'letters')).resolves.toEqual({ ok: true, answer });
    });

    it('el motor caido sigue lanzando (el panel ofrece su mensaje de error)', async () => {
        researchRequest.mockRejectedValue(new AppError('engine down', 'RESEARCH_API_ERROR', 503));
        await expect(askKnowledgeResult('¿Qué dice Buffett?', 'letters')).rejects.toThrow('engine down');
    });
});
