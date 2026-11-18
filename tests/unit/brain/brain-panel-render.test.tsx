// Preflight behavior is covered in ai/AiAvailabilityNotice.test.tsx.
vi.mock('@/components/ai/AiAvailabilityNotice', () => ({
    useAiAvailability: () => ({ canStart: true, refresh: async () => true }),
    AiAvailabilityNotice: () => null,
}));
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Rendimiento del chat: teclear en el campo de mensaje no debe volver a pintar
// (ni a parsear el markdown de) las respuestas ya mostradas. Antes cada tecla
// repintaba todo el historial: con 30 mensajes ≈ 95 ms por pulsación.
const markdownRenders = vi.fn();
vi.mock('react-markdown', () => ({
    default: ({ children }: { children: string }) => {
        markdownRenders(children);
        return <div data-testid="md">{children}</div>;
    },
}));
vi.mock('next/navigation', () => ({ usePathname: () => '/portfolio' }));
vi.mock('@/lib/actions/knowledge-chat.actions', () => ({ askKnowledge: vi.fn(), askKnowledgeResult: vi.fn() }));
vi.mock('@/lib/actions/brain.actions', () => ({ chatWithPortfolio: vi.fn() }));
vi.mock('@/lib/research/assistant-actions', () => ({ askResearchAssistantAction: vi.fn() }));

import { GlobalBrain } from '@/components/brain/GlobalBrain';
import { brainStorageKey } from '@/lib/brain/conversation';

beforeEach(() => {
    Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo;
    window.sessionStorage.clear();
    markdownRenders.mockClear();
});

describe('GlobalBrainPanel: render al teclear', () => {
    it('escribir una pregunta no repinta las respuestas anteriores', async () => {
        const messages = Array.from({ length: 10 }, (_, i) =>
            i % 2 === 0 ? { role: 'user', content: `pregunta ${i}` } : { role: 'assistant', content: `### Respuesta ${i}\n- **dato** ${i}` });
        window.sessionStorage.setItem(brainStorageKey('u1'), JSON.stringify(messages));
        render(<GlobalBrain userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir el cerebro' }));
        await screen.findByRole('dialog', { name: 'Cerebro GerarAI' });
        await screen.findByText(/Respuesta 9/);
        expect(screen.getAllByTestId('md')).toHaveLength(5);
        markdownRenders.mockClear();

        const box = screen.getByLabelText('Pregunta al cerebro');
        // 9 pulsaciones bastan para pinear la propiedad (ninguna repinta el
        // markdown); 21 caracteres multiplicaban el coste CPU del test sin
        // anadir cobertura (medido 18-nov-2026: ~45 ms por pulsacion bajo
        // contencion, el test rozaba el timeout de 5 s en el gate).
        const text = '¿cómo va?';
        for (let k = 1; k <= text.length; k++) fireEvent.change(box, { target: { value: text.slice(0, k) } });

        expect(box).toHaveValue(text);
        expect(markdownRenders).not.toHaveBeenCalled();
        // Las respuestas siguen ahí, con su contenido.
        expect(screen.getAllByTestId('md').map((n) => n.textContent)).toEqual(
            messages.filter((m) => m.role === 'assistant').map((m) => m.content));
    });
});
