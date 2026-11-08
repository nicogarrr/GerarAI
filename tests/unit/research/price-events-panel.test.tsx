import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PriceEventsPanel } from '@/components/research/PriceEventsPanel';
import type { PriceEvent } from '@/lib/market/price-events';

const EVENTS: PriceEvent[] = [
    { id: 'news-1', date: '2026-11-06', kind: 'news', title: 'Titular largo de ejemplo para la lista', detail: null, source: 'Yahoo Finance', source_url: 'https://example.com/noticia' },
];

const t = ((key: string) => key) as never;

function renderPanel() {
    return render(
        <PriceEventsPanel
            events={EVENTS}
            hiddenKinds={new Set()}
            onToggleKind={() => {}}
            onFocus={() => {}}
            hourly={false}
            t={t}
            formatMarketDate={(date: string) => date}
        />,
    );
}

describe('lista de eventos del gráfico en móvil', () => {
    it('el titular baja a su propia línea en pantallas estrechas', () => {
        renderPanel();
        const title = screen.getByText('Titular largo de ejemplo para la lista');
        // Sin basis-full el titular se quedaba con ~60 px a 390 px y salía
        // una palabra por línea; sm:basis-auto conserva la línea en escritorio.
        expect(title.className).toContain('basis-full');
        expect(title.className).toContain('sm:basis-auto');
        expect(title.className).toContain('flex-1');
    });

    it('la fuente enlaza y abre en pestaña nueva', () => {
        renderPanel();
        const source = screen.getByRole('link', { name: 'Yahoo Finance' });
        expect(source.getAttribute('target')).toBe('_blank');
        expect(source.getAttribute('rel')).toContain('noreferrer');
    });
});
