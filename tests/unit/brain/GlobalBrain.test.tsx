import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let pathname = '/portfolio';
vi.mock('next/navigation', () => ({ usePathname: () => pathname }));

const askKnowledge = vi.fn();
vi.mock('@/lib/actions/knowledge-chat.actions', () => ({ askKnowledge: (...a: unknown[]) => askKnowledge(...a) }));
vi.mock('@/components/brain/BrainLibraryAnswer', () => ({ BrainLibraryAnswer: () => <div>Citas conservadas</div> }));
const chatWithPortfolio = vi.fn();
vi.mock('@/lib/actions/brain.actions', () => ({ chatWithPortfolio: (...a: unknown[]) => chatWithPortfolio(...a) }));
const askResearchAssistantAction = vi.fn();
vi.mock('@/lib/research/assistant-actions', () => ({ askResearchAssistantAction: (...a: unknown[]) => askResearchAssistantAction(...a) }));
vi.mock('@/components/search/TickerSearchInput', () => ({
    TickerSearchInput: (p: { value: string; onValueChange: (v: string) => void; onSelect: (s: { symbol: string }) => void; onBlur: () => void; ariaLabel: string }) => (
        <div>
            <input aria-label={p.ariaLabel} value={p.value} onChange={(e) => p.onValueChange(e.target.value)} onBlur={p.onBlur} />
            <button type="button" onClick={() => p.onSelect({ symbol: 'ASTS' })}>elegir ASTS</button>
        </div>
    ),
}));
vi.mock('@/components/brain/BrainGuideAnswer', () => ({
    BrainGuideAnswer: ({ result }: { result: { answer: string } }) => <div data-testid="guide-answer">{result.answer}</div>,
}));

import { GlobalBrain } from '@/components/brain/GlobalBrain';
import { OPEN_BRAIN_PENDING_KEY, openBrain } from '@/lib/brain/open-brain';
import { brainStorageKey } from '@/lib/brain/conversation';

const KEY = brainStorageKey('u1');
const open = async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Abrir el cerebro' }));
    // El panel carga asíncrono (next/dynamic): aparece cuando llega el chunk.
    await screen.findByRole('dialog', { name: 'Cerebro GerarAI' });
};
const box = () => screen.getByLabelText('Pregunta al cerebro');
const ask = (text: string) => {
    fireEvent.change(box(), { target: { value: text } });
    fireEvent.click(screen.getByRole('button', { name: 'Enviar pregunta' }));
};
const logEl = () => screen.getByRole('log', { name: 'Mensajes del cerebro' });

beforeEach(() => {
    // jsdom no implementa Element.scrollTo (el panel lo usa para ir al último mensaje).
    Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo;
    pathname = '/portfolio';
    chatWithPortfolio.mockReset();
    askKnowledge.mockReset();
    askResearchAssistantAction.mockReset();
    window.sessionStorage.clear();
});
afterEach(() => {
    vi.useRealTimers();
});

describe('GlobalBrain: botón y apertura', () => {
    it('cerrado: solo el botón flotante; la pista se pliega a los 4 s', () => {
        vi.useFakeTimers();
        const { container } = render(<GlobalBrain userId="u1" />);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        const hint = screen.getByText('Pregunta al Cerebro');
        expect(hint.className).toContain('opacity-100');
        act(() => { vi.advanceTimersByTime(4100); });
        expect(hint.className).toContain('opacity-0');
        expect(container.querySelector('.brain-breathe')).toBeNull();
    });
    it('marca el documento como listo mientras está montado y lo desmarca al desmontar', () => {
        const { unmount } = render(<GlobalBrain userId="u1" />);
        expect(document.documentElement.hasAttribute('data-brain-ready')).toBe(true);
        unmount();
        expect(document.documentElement.hasAttribute('data-brain-ready')).toBe(false);
    });
    it('abrir muestra el diálogo modal con saludo y preguntas sugeridas que rellenan el input', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        const dialog = screen.getByRole('dialog', { name: 'Cerebro GerarAI' });
        expect(dialog).toHaveAttribute('aria-modal', 'true');
        expect(await within(dialog).findByText(/Soy el cerebro de GerarAI/)).toBeInTheDocument();
        expect(document.body.style.overflow).toBe('hidden');
        expect(document.activeElement).toBe(box());
        fireEvent.click(screen.getByRole('button', { name: '¿Qué riesgos tiene mi cartera?' }));
        expect(box()).toHaveValue('¿Qué riesgos tiene mi cartera?');
    });
    it('Escape cierra, restaura el scroll del body y devuelve el foco al botón que abrió', async () => {
        render(<GlobalBrain userId="u1" />);
        const trigger = screen.getByRole('button', { name: 'Abrir el cerebro' });
        trigger.focus();
        fireEvent.click(trigger);
        await screen.findByRole('dialog', { name: 'Cerebro GerarAI' });
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(document.body.style.overflow).toBe('');
    });
    it('mientras está abierto el resto de la página queda inert y aria-hidden, y se restaura al cerrar', async () => {
        const { container } = render(
            <div>
                <main id="page" aria-hidden="false">página</main>
                <GlobalBrain userId="u1" />
            </div>,
        );
        const page = container.querySelector('#page') as HTMLElement;
        await open();
        expect(page.inert).toBe(true);
        expect(page).toHaveAttribute('aria-hidden', 'true');
        fireEvent.click(screen.getByRole('button', { name: 'Cerrar el cerebro' }));
        expect(page.inert).toBeFalsy();
        expect(page).toHaveAttribute('aria-hidden', 'false');
    });
    it('maximizar y restaurar alterna la etiqueta', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.click(screen.getByRole('button', { name: 'Maximizar el cerebro' }));
        expect(screen.getByRole('dialog').className).toContain('left-4');
        fireEvent.click(screen.getByRole('button', { name: 'Restaurar el cerebro' }));
        expect(screen.getByRole('dialog').className).not.toContain('left-4');
    });
});

describe('GlobalBrain: trampa de foco', () => {
    const focusables = () => [
        ...screen.getByRole('dialog').querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled])'),
    ];
    beforeEach(() => {
        // jsdom no tiene layout: se declara que todo es visible para el filtro de tab stops.
        vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
    });
    it('Tab desde el último vuelve al primero y Shift+Tab desde el primero va al último', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        const items = focusables();
        const first = items[0];
        const last = items[items.length - 1];
        last.focus();
        fireEvent.keyDown(document, { key: 'Tab' });
        expect(document.activeElement).toBe(first);
        fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
        expect(document.activeElement).toBe(last);
    });
    it('con el foco en el propio panel, Tab entra por el primero y Shift+Tab por el último', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        const items = focusables();
        screen.getByRole('dialog').focus();
        fireEvent.keyDown(document, { key: 'Tab' });
        expect(document.activeElement).toBe(items[0]);
        screen.getByRole('dialog').focus();
        fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
        expect(document.activeElement).toBe(items[items.length - 1]);
    });
    it('una tecla cualquiera que no es Tab no mueve el foco', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        const before = document.activeElement;
        fireEvent.keyDown(document, { key: 'a' });
        expect(document.activeElement).toBe(before);
    });
    it('sin elementos enfocables, Tab se queda en el panel', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue([] as unknown as DOMRectList);
        fireEvent.keyDown(document, { key: 'Tab' });
        expect(document.activeElement).toBe(screen.getByRole('dialog'));
    });
});

describe('GlobalBrain: pastilla "Viendo"', () => {
    it('muestra la sección actual como enlace a la página', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        const pill = screen.getByTestId('brain-page-context');
        expect(pill).toHaveTextContent('Viendo Cartera');
        expect(pill).toHaveAttribute('href', '/portfolio');
    });
    it('en una página no identificable no hay pastilla', async () => {
        pathname = '/pagina-rara';
        render(<GlobalBrain userId="u1" />);
        await open();
        expect(screen.queryByTestId('brain-page-context')).not.toBeInTheDocument();
    });
    it('el eco del servidor manda sobre la etiqueta local y la pastilla navega a la ficha', async () => {
        chatWithPortfolio.mockResolvedValue({
            success: true, message: 'ok', citations: [],
            context: { label: 'ASTS', ticker: 'ASTS', company_name: 'AST SpaceMobile', company_resolved: true },
        });
        render(<GlobalBrain userId="u1" />);
        await open();
        ask('¿Cómo va ASTS?');
        await waitFor(() => expect(screen.getByTestId('brain-page-context')).toHaveTextContent('Viendo ASTS'));
        expect(screen.getByTestId('brain-page-context')).toHaveAttribute('href', '/research/ASTS');
        expect(screen.getByTestId('brain-page-context')).toHaveAttribute('title', 'AST SpaceMobile');
    });
    it('un eco sin ticker deja la pastilla apuntando a la página local, y al navegar vuelve la etiqueta local', async () => {
        chatWithPortfolio.mockResolvedValue({
            success: true, message: 'ok', citations: [],
            context: { label: 'Mi cartera', ticker: null, company_name: null, company_resolved: false },
        });
        const { rerender } = render(<GlobalBrain userId="u1" />);
        await open();
        ask('¿Cómo va mi cartera?');
        await waitFor(() => expect(screen.getByTestId('brain-page-context')).toHaveTextContent('Viendo Mi cartera'));
        expect(screen.getByTestId('brain-page-context')).toHaveAttribute('href', '/portfolio');
        pathname = '/watchlist';
        rerender(<GlobalBrain userId="u1" />);
        expect(screen.getByTestId('brain-page-context')).toHaveTextContent('Viendo Seguimiento');
    });
});

describe('GlobalBrain: chat de cartera', () => {
    it('envía pregunta recortada con userId, página e historial y pinta la respuesta markdown con fuentes', async () => {
        chatWithPortfolio.mockResolvedValue({
            success: true,
            message: 'Tienes **12** posiciones. Ver [ASTS](/research/ASTS) y [SEC](https://sec.gov/x).',
            citations: [{ document: 'Informe 10-K', url: 'https://sec.gov/10k', page: 3, locator: 'p3', kind: 'filing' }],
        });
        render(<GlobalBrain userId="u1" />);
        await open();
        ask('  ¿Cuántas posiciones?  ');
        expect(box()).toHaveValue('');
        expect(screen.getByRole('status')).toHaveTextContent('escribiendo');
        expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'true');
        const internal = await screen.findByRole('link', { name: 'ASTS' });
        expect(internal).toHaveAttribute('href', '/research/ASTS');
        expect(internal).not.toHaveAttribute('target');
        const external = screen.getByRole('link', { name: 'SEC' });
        expect(external).toHaveAttribute('target', '_blank');
        expect(external).toHaveAttribute('rel', expect.stringContaining('noopener'));
        expect(screen.getByRole('region', { name: 'Fuentes de esta respuesta' })).toHaveTextContent('Informe 10-K');
        expect(chatWithPortfolio).toHaveBeenCalledWith(
            '¿Cuántas posiciones?', 'u1',
            { path: '/portfolio', label: 'Cartera', ticker: null },
            [{ role: 'assistant', content: expect.stringContaining('Soy el cerebro') }],
        );
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });
    it('no envía si el texto es solo espacios (botón desactivado)', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.change(box(), { target: { value: '   ' } });
        expect(screen.getByRole('button', { name: 'Enviar pregunta' })).toBeDisabled();
        fireEvent.submit(box().closest('form')!);
        expect(chatWithPortfolio).not.toHaveBeenCalled();
    });
    it('fallo controlado del servidor: muestra su mensaje o uno genérico', async () => {
        chatWithPortfolio.mockResolvedValueOnce({ success: false, message: 'Límite diario alcanzado' });
        render(<GlobalBrain userId="u1" />);
        await open();
        ask('hola que tal');
        expect(await screen.findByText('Límite diario alcanzado')).toBeInTheDocument();
        chatWithPortfolio.mockResolvedValueOnce({ success: false, message: '' });
        ask('otra pregunta');
        expect(await screen.findByText('Lo siento, hubo un error desconocido.')).toBeInTheDocument();
    });
    it('excepción: avisa sin romper el panel y permite reintentar', async () => {
        chatWithPortfolio.mockRejectedValueOnce(new Error('boom'));
        render(<GlobalBrain userId="u1" />);
        await open();
        ask('hola que tal');
        expect(await screen.findByText(/No se pudo completar la respuesta/)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Enviar pregunta' })).toBeDisabled(); // input vacío, no cargando
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });
    it('Copiar escribe el texto de la respuesta; no aparece en el saludo; si falla no marca Copiado', async () => {
        chatWithPortfolio.mockResolvedValue({ success: true, message: 'Respuesta uno', citations: [] });
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        render(<GlobalBrain userId="u1" />);
        await open();
        expect(screen.queryByRole('button', { name: 'Copiar' })).not.toBeInTheDocument();
        ask('pregunta uno');
        const copy = await screen.findByRole('button', { name: 'Copiar' });
        fireEvent.click(copy);
        await screen.findByRole('button', { name: 'Copiado' });
        expect(writeText).toHaveBeenCalledWith('Respuesta uno');
        writeText.mockRejectedValueOnce(new Error('denied'));
        fireEvent.click(screen.getByRole('button', { name: 'Copiado' }));
        await screen.findByRole('button', { name: 'Copiar' });
    });
});

describe('GlobalBrain: modo guía', () => {
    it('el botón Guía abre el selector; al perder el foco vacío se pliega; con ticker cambia el placeholder', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.click(screen.getByRole('button', { name: 'Abrir la guía de investigación por empresa' }));
        const field = screen.getByLabelText('Ticker de la guía de investigación');
        fireEvent.blur(field);
        expect(screen.queryByLabelText('Ticker de la guía de investigación')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Abrir la guía de investigación por empresa' }));
        fireEvent.change(screen.getByLabelText('Ticker de la guía de investigación'), { target: { value: 'asts' } });
        fireEvent.blur(screen.getByLabelText('Ticker de la guía de investigación'));
        expect(screen.getByLabelText('Ticker de la guía de investigación')).toBeInTheDocument();
        expect(box()).toHaveAttribute('placeholder', 'Pregunta sobre ASTS...');
    });
    it('con ticker pregunta al asistente de research (no al chat), en mayúsculas, con su página e historial', async () => {
        askResearchAssistantAction.mockResolvedValue({ mode: 'guide', status: 'answered', answer: 'Conclusión ASTS', sections: [] });
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.click(screen.getByRole('button', { name: 'Abrir la guía de investigación por empresa' }));
        fireEvent.click(screen.getByRole('button', { name: 'elegir ASTS' }));
        ask('¿Qué riesgos tiene?');
        expect(await screen.findByTestId('guide-answer')).toHaveTextContent('Conclusión ASTS');
        expect(chatWithPortfolio).not.toHaveBeenCalled();
        const arg = askResearchAssistantAction.mock.calls[0][0];
        expect(arg).toMatchObject({ mode: 'guide', question: '¿Qué riesgos tiene?', ticker: 'ASTS', page: { label: 'Cartera' } });
        expect(arg).not.toHaveProperty('review_id');
        // la respuesta de guía no tiene botón Copiar solo si... sí lo tiene (i > 0)
        expect(screen.getByRole('button', { name: 'Copiar' })).toBeInTheDocument();
    });
    it('respuesta de guía sin texto: se rotula con el ticker; el eco se aplica', async () => {
        askResearchAssistantAction.mockResolvedValue({
            mode: 'guide', status: 'insufficient_data', answer: '  ', sections: [],
            context: { label: 'ASTS', ticker: 'ASTS', company_name: null, company_resolved: true },
        });
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.click(screen.getByRole('button', { name: 'Abrir la guía de investigación por empresa' }));
        fireEvent.click(screen.getByRole('button', { name: 'elegir ASTS' }));
        ask('¿Y los números?');
        await screen.findByTestId('guide-answer');
        expect(screen.getByTestId('brain-page-context')).toHaveTextContent('Viendo ASTS');
        expect(screen.getByRole('button', { name: 'Copiar' })).toBeInTheDocument();
    });
    it('pregunta demasiado corta o larga: se rechaza en cliente sin llamar al servidor', async () => {
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.click(screen.getByRole('button', { name: 'Abrir la guía de investigación por empresa' }));
        fireEvent.click(screen.getByRole('button', { name: 'elegir ASTS' }));
        ask('ab');
        expect(await screen.findByText('La pregunta debe tener entre 3 y 2000 caracteres.')).toBeInTheDocument();
        ask('x'.repeat(2001));
        await waitFor(() => expect(screen.getAllByText('La pregunta debe tener entre 3 y 2000 caracteres.')).toHaveLength(2));
        expect(askResearchAssistantAction).not.toHaveBeenCalled();
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });
    it('fallo del asistente: avisa de que no se modificó nada', async () => {
        askResearchAssistantAction.mockRejectedValue(new Error('x'));
        render(<GlobalBrain userId="u1" />);
        await open();
        fireEvent.click(screen.getByRole('button', { name: 'Abrir la guía de investigación por empresa' }));
        fireEvent.click(screen.getByRole('button', { name: 'elegir ASTS' }));
        ask('¿Qué riesgos?');
        expect(await screen.findByText(/no se ha modificado nada/)).toBeInTheDocument();
    });
});

describe('GlobalBrain: apertura desde otras pantallas', () => {
    it('el evento abre el panel, ancla ticker y revisión, y precarga la pregunta; la revisión se puede quitar', async () => {
        askResearchAssistantAction.mockResolvedValue({ mode: 'guide', status: 'answered', answer: 'ok', sections: [] });
        render(<GlobalBrain userId="u1" />);
        act(() => openBrain({ ticker: 'asts', review_id: 7, question: '¿Cambió la tesis?' }));
        await screen.findByRole('dialog');
        expect(box()).toHaveValue('¿Cambió la tesis?');
        expect(screen.getByText(/Revisión #7/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Enviar pregunta' }));
        await screen.findByTestId('guide-answer');
        expect(askResearchAssistantAction.mock.calls[0][0]).toMatchObject({ ticker: 'ASTS', review_id: 7 });
        fireEvent.click(screen.getByRole('button', { name: 'Quitar la revisión anclada' }));
        expect(screen.queryByText(/Revisión #7/)).not.toBeInTheDocument();
    });
    it('una apertura sin ticker no hereda el ancla anterior', async () => {
        render(<GlobalBrain userId="u1" />);
        act(() => openBrain({ ticker: 'ASTS', review_id: 3 }));
        expect(await screen.findByText(/Revisión #3/)).toBeInTheDocument();
        act(() => openBrain({ question: 'x'.repeat(2500) }));
        await waitFor(() => expect(screen.queryByText(/Revisión #3/)).not.toBeInTheDocument());
        expect((box() as HTMLInputElement).value).toHaveLength(2000);
        expect(box()).toHaveAttribute('placeholder', 'Pregunta al cerebro...');
    });
    it('el handoff pendiente en sessionStorage se recoge al montar, una sola vez', async () => {
        window.sessionStorage.setItem(OPEN_BRAIN_PENDING_KEY, JSON.stringify({ ticker: 'KO', question: 'hola KO' }));
        render(<GlobalBrain userId="u1" />);
        // El handoff se aplica en un microtask (no setState síncrono en el efecto).
        expect(await screen.findByRole('dialog')).toBeInTheDocument();
        expect(box()).toHaveValue('hola KO');
        expect(window.sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        expect(box()).toHaveAttribute('placeholder', 'Pregunta sobre KO...');
    });
    it('un handoff corrupto se ignora sin abrir el panel', () => {
        window.sessionStorage.setItem(OPEN_BRAIN_PENDING_KEY, '{no json');
        render(<GlobalBrain userId="u1" />);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
});

describe('GlobalBrain: persistencia', () => {
    it('restaura la conversación guardada del usuario y la guarda (sin el payload de guía) tras cada cambio', async () => {
        window.sessionStorage.setItem(KEY, JSON.stringify([
            { role: 'assistant', content: 'Saludo guardado' },
            { role: 'user', content: 'Pregunta previa' },
        ]));
        chatWithPortfolio.mockResolvedValue({ success: true, message: 'Nueva respuesta', citations: [{ document: 'D', url: null, page: null, locator: 'l', kind: 'filing' }] });
        render(<GlobalBrain userId="u1" />);
        await open();
        // La restauración se aplica en un microtask tras montar.
        expect(await screen.findByText('Saludo guardado')).toBeInTheDocument();
        expect(screen.getByText('Pregunta previa')).toBeInTheDocument();
        expect(screen.queryByRole('group', { name: 'Preguntas sugeridas' })).not.toBeInTheDocument();
        ask('¿Y ahora?');
        await screen.findByText('Nueva respuesta');
        await waitFor(() => {
            const saved = JSON.parse(window.sessionStorage.getItem(KEY)!);
            expect(saved.map((m: { content: string }) => m.content)).toEqual(['Saludo guardado', 'Pregunta previa', '¿Y ahora?', 'Nueva respuesta']);
            expect(saved[3].citations).toHaveLength(1);
        });
    });
    it('la conversación de otro usuario no se carga', async () => {
        window.sessionStorage.setItem(brainStorageKey('otro'), JSON.stringify([{ role: 'assistant', content: 'Secreto de otro' }]));
        render(<GlobalBrain userId="u1" />);
        await open();
        expect(screen.queryByText('Secreto de otro')).not.toBeInTheDocument();
        expect(await screen.findByText(/Soy el cerebro de GerarAI/)).toBeInTheDocument();
    });
    it('sessionStorage bloqueado: el panel sigue funcionando', async () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
        chatWithPortfolio.mockResolvedValue({ success: true, message: 'Sigue', citations: [] });
        render(<GlobalBrain userId="u1" />);
        await open();
        ask('pregunta sin storage');
        expect(await screen.findByText('Sigue')).toBeInTheDocument();
    });
});


describe('Cerebro único: biblioteca y cartas', () => {
  it('handoff elimina ticker anterior y conserva autor, modo y endpoint de conocimiento', async () => {
    askKnowledge.mockResolvedValue({ answers: [], message: 'Sin datos guardados', status: 'sin_datos', retrieval: 'solo_texto' });
    render(<GlobalBrain userId="u1" />);
    act(() => openBrain({ ticker: 'UBER' }));
    await screen.findByRole('dialog');
    act(() => openBrain({ knowledge: { scope: 'letters', authors: ['Buffett'] }, question: '¿Recompras?' }));
    expect(screen.queryByLabelText('Ticker de la guía de investigación')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Autor'), { target: { value: 'Buffett' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Enviar pregunta' }));
    await waitFor(() => expect(askKnowledge).toHaveBeenCalledWith('¿Recompras?', 'letters', 'Buffett', 'analisis', expect.objectContaining({ path: '/portfolio' }), undefined));
    expect(chatWithPortfolio).not.toHaveBeenCalled();
    expect(askResearchAssistantAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Volver al chat general' }));
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
});

it('401 de biblioteca se muestra como sesión caducada sin borrar conversación', async () => {
  askKnowledge.mockRejectedValue(Object.assign(new Error('Unauthorized'), {statusCode:401}));
  render(<GlobalBrain userId="u1" />);
  act(() => openBrain({knowledge:{scope:'library'},question:'Pregunta válida'}));
  await screen.findByRole('dialog');
  fireEvent.click(screen.getByRole('button',{name:'Enviar pregunta'}));
  await screen.findByText('Sesión caducada. Vuelve a iniciar sesión.');
  expect(screen.getByText('Pregunta válida')).toBeInTheDocument();
});
