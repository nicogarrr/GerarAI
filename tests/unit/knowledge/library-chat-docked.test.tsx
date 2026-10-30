import { fireEvent, render, screen } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { LibraryChat } from '@/app/(root)/inversores/_components/LibraryChat';
import { markBrainReady, readLibraryContext } from '@/lib/brain/open-brain';

// Nico (30-oct): «no me gusta nada el Cerebro ahí en medio». La Biblioteca ya
// no reserva un panel de 780 px en mitad de la página: deja un marcador oculto
// con su contexto y un botón compacto que abre el Cerebro flotante.
describe('LibraryChat: el Cerebro queda acoplado abajo a la derecha', () => {
    afterEach(() => markBrainReady(false));

    it('el HTML del servidor no reserva ningún panel incrustado', () => {
        const html = renderToString(<LibraryChat scope="library" />);
        expect(html).not.toContain('h-[min(780px,80dvh)]');
        expect(html).not.toContain('min-h-[520px]');
        expect(html).not.toContain('brain-library-slot');
        expect(html).not.toContain('brain-slot-skeleton');
        expect(html).toContain('id="brain-library-context"');
        expect(html).toContain('Preguntar a la biblioteca');
    });

    it('el marcador oculto lleva el contexto saneado de la carta', () => {
        const { container } = render(<LibraryChat scope="letters" authors={['Buffett']} documentId={7} documentTitle="Carta 1987" />);
        const marker = container.querySelector<HTMLElement>('#brain-library-context');
        expect(marker).not.toBeNull();
        expect(marker!.hidden).toBe(true);
        expect(readLibraryContext(marker)).toEqual({ scope: 'letters', authors: ['Buffett'], documentId: 7, documentTitle: 'Carta 1987' });
    });

    it('el botón abre el Cerebro con el contexto de la biblioteca', () => {
        markBrainReady(true);
        const seen: unknown[] = [];
        const listener = vi.fn((e: Event) => seen.push((e as CustomEvent).detail));
        window.addEventListener('gerarai:open-brain', listener);
        render(<LibraryChat scope="library" />);
        fireEvent.click(screen.getByRole('button', { name: 'Preguntar a la biblioteca' }));
        window.removeEventListener('gerarai:open-brain', listener);
        expect(seen).toEqual([{ knowledge: { scope: 'library', authors: [] } }]);
    });
});
