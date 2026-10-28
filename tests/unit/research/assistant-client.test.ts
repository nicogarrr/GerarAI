import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, researchRequest, trimBrainHistory } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(async () => ({ id: 'user-1' })),
    researchRequest: vi.fn(async (_path: string, _init?: { method?: string; body?: unknown }) => ({})),
    trimBrainHistory: vi.fn((history: unknown) => history ?? []),
}));
// 'server-only' solo existe en el bundler de Next; en Vitest se anula.
vi.mock('server-only', () => ({}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/research/client', () => ({
    researchRequest,
    jsonBody: (body: unknown) => JSON.stringify(body),
}));
vi.mock('@/lib/brain/history', () => ({ trimBrainHistory }));

import { askResearchAssistant, getGuideContext } from '@/lib/research/assistant-client';

const compatibleResponse = {
    mode: 'explore',
    status: 'answered',
    answer: 'respuesta',
    sections: [],
    citations: [],
    missing_data: [],
    suggested_next_steps: [],
    review_id: null,
    writeback: false,
} as const;

beforeEach(() => {
    vi.clearAllMocks();
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
    researchRequest.mockResolvedValue({ ...compatibleResponse });
});

describe('askResearchAssistant', () => {
    it('exige sesión antes de llamar al backend', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('sin sesión'));
        await expect(askResearchAssistant({ mode: 'explore', question: '¿qué es ASTS?' })).rejects.toThrow('sin sesión');
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('normaliza pregunta y ticker y pega solo al endpoint nuevo sin escritura', async () => {
        researchRequest.mockResolvedValue({ ...compatibleResponse, mode: 'guide' });
        await askResearchAssistant({ mode: 'guide', question: '  ¿cómo valoro esto?  ', ticker: ' asts ', review_id: 7 });
        expect(researchRequest).toHaveBeenCalledWith('/api/research/assistant', expect.objectContaining({ method: 'POST' }));
        const body = JSON.parse(String(researchRequest.mock.calls[0]?.[1]?.body));
        expect(body).toMatchObject({ mode: 'guide', question: '¿cómo valoro esto?', ticker: 'ASTS', review_id: 7 });
    });

    it('rechaza preguntas fuera de rango, modos desconocidos y guía sin ticker', async () => {
        await expect(askResearchAssistant({ mode: 'explore', question: 'ok' })).rejects.toThrow('entre 3 y 2000');
        await expect(askResearchAssistant({ mode: 'otro' as never, question: '¿qué es ASTS?' })).rejects.toThrow('Modo de investigación no válido');
        await expect(askResearchAssistant({ mode: 'guide', question: '¿qué es ASTS?' })).rejects.toThrow('necesita un ticker');
        await expect(askResearchAssistant({ mode: 'explore', question: '¿qué es ASTS?', review_id: 3 })).rejects.toThrow('Revisión no válida');
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('fallo cerrado: una respuesta con writeback o campos ajenos se rechaza', async () => {
        researchRequest.mockResolvedValue({ ...compatibleResponse, writeback: true });
        await expect(askResearchAssistant({ mode: 'explore', question: '¿qué es ASTS?' })).rejects.toThrow('incompatible con el contrato de solo lectura');
        researchRequest.mockResolvedValue({ ...compatibleResponse, sections: 'no-array' });
        await expect(askResearchAssistant({ mode: 'explore', question: '¿qué es ASTS?' })).rejects.toThrow('incompatible con el contrato de solo lectura');
        researchRequest.mockResolvedValue({ ...compatibleResponse, mode: 'guide' });
        await expect(askResearchAssistant({ mode: 'explore', question: '¿qué es ASTS?' })).rejects.toThrow('incompatible con el contrato de solo lectura');
    });
});

describe('getGuideContext', () => {
    it('normaliza el ticker y lo codifica en la ruta', async () => {
        researchRequest.mockResolvedValue({ ticker: 'ASTS' });
        await getGuideContext('  asts ');
        expect(researchRequest).toHaveBeenCalledWith('/api/research/guide-context?ticker=ASTS');
    });

    it('sin ticker no llama al backend', async () => {
        await expect(getGuideContext('   ')).rejects.toThrow('Ticker obligatorio');
        expect(researchRequest).not.toHaveBeenCalled();
    });
});
