import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-markdown', () => ({
    default: ({ children }: { children: string }) => <div>{children}</div>,
}));
vi.mock('next/navigation', () => ({ usePathname: () => '/portfolio' }));
vi.mock('@/lib/actions/knowledge-chat.actions', () => ({ askKnowledge: vi.fn(), askKnowledgeResult: vi.fn() }));
vi.mock('@/lib/actions/brain.actions', () => ({ chatWithPortfolio: vi.fn() }));
vi.mock('@/lib/research/assistant-actions', () => ({ askResearchAssistantAction: vi.fn() }));

import { GlobalBrainPanel, type BrainMessage } from '@/components/brain/GlobalBrainPanel';

const writeText = vi.fn();
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');

const messages: BrainMessage[] = [
    { role: 'user', content: 'Pregunta' },
    { role: 'assistant', content: 'Respuesta' },
];

function renderPanel() {
    return render(
        <GlobalBrainPanel
            userId="u1"
            knowledge={null}
            openDetail={null}
            messages={messages}
            setMessages={vi.fn()}
            onClose={vi.fn()}
            onClearKnowledge={vi.fn()}
        />,
    );
}

beforeEach(() => {
    Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo;
    writeText.mockReset();
    Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText },
    });
});

afterEach(() => {
    if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard);
    else Reflect.deleteProperty(navigator, 'clipboard');
});

describe('GlobalBrainPanel: copiar mensaje', () => {
    it('dice que no se pudo copiar cuando el portapapeles rechaza la escritura', async () => {
        writeText.mockRejectedValueOnce(new Error('denied'));
        renderPanel();

        fireEvent.click(await screen.findByRole('button', { name: 'Copiar' }));

        expect(await screen.findByText('No se pudo copiar')).toBeVisible();
        expect(screen.getByRole('alert')).toHaveTextContent('No se pudo copiar');
    }, 20000);

    it('sigue mostrando Copiado cuando la escritura funciona', async () => {
        writeText.mockResolvedValueOnce(undefined);
        renderPanel();

        fireEvent.click(await screen.findByRole('button', { name: 'Copiar' }));

        expect(await screen.findByRole('button', { name: 'Copiado' })).toBeVisible();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    }, 20000);
});
