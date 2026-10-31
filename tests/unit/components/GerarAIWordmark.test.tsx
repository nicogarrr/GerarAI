import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { GerarAIWordmark } from '@/components/GerarAIWordmark';

// Rediseño 1-nov-2026: el wordmark usa el monograma propio (la G con la
// barra de gráfica), no un icono lucide de stock.
describe('GerarAIWordmark', () => {
    it('pinta el monograma inline (arco de la G + barra) y no depende de lucide', () => {
        const { container } = render(<GerarAIWordmark />);
        const svg = container.querySelector('svg');
        expect(svg).not.toBeNull();
        const html = svg!.innerHTML;
        expect(html).toContain('M17.39 18.89');
        expect(html).toContain('M12.4 12H18.8V14.3');
    });

    it('modo normal enseña el texto y compact lo oculta', () => {
        const full = render(<GerarAIWordmark />);
        expect(full.container.textContent).toContain('Gerar');
        const compact = render(<GerarAIWordmark compact />);
        expect(compact.container.textContent).not.toContain('Gerar');
    });
});
