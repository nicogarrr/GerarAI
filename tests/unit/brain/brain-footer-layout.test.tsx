import { readFileSync } from 'node:fs';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BRAIN_CHAT_MODEL_KEY } from '@/lib/brain/chat-model';

// Estado de disponibilidad controlable por test.
const avail = vi.hoisted(() => ({
    current: { canStart: true, refresh: async () => true, status: null as null | { state: string }, failed: false, checking: false },
}));
const chatWithPortfolio = vi.hoisted(() => vi.fn());
vi.mock('@/components/ai/AiAvailabilityNotice', () => ({
    useAiAvailability: () => avail.current,
    AiAvailabilityNotice: () => <div data-testid="ai-notice" />,
}));
vi.mock('next/navigation', () => ({ usePathname: () => '/portfolio' }));
vi.mock('@/lib/actions/knowledge-chat.actions', () => ({ askKnowledge: vi.fn(), askKnowledgeResult: vi.fn() }));
vi.mock('@/lib/actions/brain.actions', () => ({ chatWithPortfolio }));
vi.mock('@/lib/research/assistant-actions', () => ({ askResearchAssistantAction: vi.fn() }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => null }));
vi.mock('@/components/brain/BrainGuideAnswer', () => ({ BrainGuideAnswer: () => null }));
vi.mock('@/components/brain/BrainLibraryAnswer', () => ({ BrainLibraryAnswer: () => null }));
vi.mock('react-markdown', () => ({ default: ({ children }: { children: string }) => <div>{children}</div> }));

import { GlobalBrain } from '@/components/brain/GlobalBrain';

const src = (p: string) => readFileSync(p, 'utf8');

async function open() {
    fireEvent.click(screen.getByRole('button', { name: 'Abrir el cerebro' }));
    await screen.findByRole('dialog', { name: 'Cerebro GerarAI' });
}

beforeEach(() => {
    Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo;
    window.sessionStorage.clear();
    window.localStorage.clear();
    chatWithPortfolio.mockReset();
    chatWithPortfolio.mockResolvedValue({ success: true, message: 'Respuesta', citations: [] });
    avail.current = { canStart: true, refresh: async () => true, status: null, failed: false, checking: false };
});

// Pie del panel Cerebro (producto, 17-nov-2026): ni cartel de
// disponibilidad (el error sale en el propio mensaje de respuesta) ni
// selector de modelo (se elige en Ajustes > LLM). El pie queda solo con
// el input.
describe('GlobalBrainPanel: pie solo con el input', () => {
    it('guard: el panel no pinta AiAvailabilityNotice ni el selector de modelo', () => {
        const s = src('components/brain/GlobalBrainPanel.tsx');
        expect(s).not.toContain('<AiAvailabilityNotice');
        expect(s).not.toContain("brain.panel.modelLabel");
        expect(s).toContain('readBrainChatModel');
        expect(s).toContain('useAiAvailability');
    });

    it('sin fallo no pinta cartel ni selector', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        expect(screen.queryByTestId('ai-notice')).not.toBeInTheDocument();
        expect(screen.queryByRole('combobox', { name: 'Modelo del chat general' })).not.toBeInTheDocument();
    });

    it('con IA en pausa tampoco pinta cartel (el fallo sale en el mensaje de respuesta)', async () => {
        avail.current = { canStart: false, refresh: async () => false, status: { state: 'paused' }, failed: false, checking: false };
        render(<GlobalBrain userId="u1" />);
        await open();
        expect(screen.queryByTestId('ai-notice')).not.toBeInTheDocument();
    });

    it('lee el modelo de la preferencia local al abrirse y lo envía en el chat', async () => {
        window.localStorage.setItem(BRAIN_CHAT_MODEL_KEY, 'hy4-flash-free');
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.change(screen.getByLabelText('Pregunta al cerebro'), { target: { value: 'Consulta con HY' } });
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Enviar pregunta' }));
        });
        expect(chatWithPortfolio).toHaveBeenCalled();
        expect(chatWithPortfolio.mock.calls[0][4]).toBe('hy4-flash-free');
    });

    it('sin preferencia guardada el chat va con el modelo por defecto', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.change(screen.getByLabelText('Pregunta al cerebro'), { target: { value: 'Consulta con defecto' } });
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Enviar pregunta' }));
        });
        expect(chatWithPortfolio.mock.calls[0]).toHaveLength(4);
    });
});
