import { act, render } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { LibraryChat } from '@/app/(root)/inversores/_components/LibraryChat';

// CLS de /knowledge (0,15 escritorio / 0,28 móvil, build de producción): el
// hueco del Cerebro nacía con 0 px y el panel (h-[min(780px,80dvh)]
// min-h-[520px]) empujaba la pestaña Biblioteca al portarse.
describe('LibraryChat: alto reservado para el Cerebro embebido', () => {
    it('el HTML del servidor ya trae el contenedor con el alto del panel y un esqueleto', () => {
        const html = renderToString(<LibraryChat scope="library" />);
        expect(html).toContain('h-[min(780px,80dvh)]');
        expect(html).toContain('min-h-[520px]');
        expect(html).toContain('data-testid="brain-slot-skeleton"');
        // El hueco del portal sigue siendo solo de cliente (sin mismatch).
        expect(html).not.toContain('brain-library-slot');
    });

    it('el esqueleto desaparece cuando el Cerebro ocupa el hueco', async () => {
        const { container, queryByTestId } = render(<LibraryChat scope="library" />);
        const slot = container.querySelector('#brain-library-slot');
        expect(slot).not.toBeNull();
        expect(queryByTestId('brain-slot-skeleton')).not.toBeNull();
        await act(async () => {
            const panel = document.createElement('div');
            panel.className = 'relative h-[min(780px,80dvh)] min-h-[520px] w-full';
            slot!.appendChild(panel);
            await Promise.resolve();
        });
        expect(queryByTestId('brain-slot-skeleton')).toBeNull();
    });
});
