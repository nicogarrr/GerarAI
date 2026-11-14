import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
            formatMarketDate={(date) => String(date)}
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


it('shows earnings date warnings without requiring an extra click', () => {
    const events: PriceEvent[] = [{ id: 'estimate', date: '2026-11-20', kind: 'results', title: 'Results', detail: 'Date estimated by the source; it may change', source: 'Yahoo Finance' }];
    render(<PriceEventsPanel events={events} hiddenKinds={new Set()} onToggleKind={() => {}} onFocus={() => {}} hourly={false} t={t} formatMarketDate={d => String(d)} />);
    expect(screen.getByText('Date estimated by the source; it may change')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'research.chart.detail' })).toBeNull();
});

it('supports filters, focus, and expandable source details', () => {
    const toggle = vi.fn(), focus = vi.fn();
    const event = { ...EVENTS[0], detail: 'Source detail' };
    const { rerender } = render(<PriceEventsPanel events={[event]} hiddenKinds={new Set()} onToggleKind={toggle} onFocus={focus} hourly t={t} formatMarketDate={d=>String(d)}/>);
    fireEvent.click(screen.getByRole('button', {name:'2026-11-06'}));
    expect(focus).toHaveBeenCalledWith('2026-11-06');
    fireEvent.click(screen.getByRole('button', {name:'research.chart.kindNews'}));
    expect(toggle).toHaveBeenCalledWith('news');
    fireEvent.click(screen.getByRole('button', {name:'research.chart.detail'}));
    expect(screen.getByText('Source detail')).toBeVisible();
    fireEvent.click(screen.getByRole('button', {name:'research.chart.less'}));
    expect(screen.queryByText('Source detail')).toBeNull();
    rerender(<PriceEventsPanel events={[event]} hiddenKinds={new Set(['news'])} onToggleKind={toggle} onFocus={focus} hourly t={t} formatMarketDate={d=>String(d)}/>);
    expect(screen.getByText('research.chart.eventsEmpty')).toBeVisible();
});

it('shows uncertain dividend details without a click', () => {
    const detail = 'research.chart.storedEvent.exDividendUncertain';
    render(<PriceEventsPanel events={[{ ...EVENTS[0], kind: 'ex_dividend', detail }]} hiddenKinds={new Set()} onToggleKind={() => {}} onFocus={() => {}} hourly={false} t={t} formatMarketDate={d=>String(d)}/>);
    expect(screen.getByText(detail)).toBeVisible();
    expect(screen.queryByRole('button', {name: 'research.chart.detail'})).toBeNull();
});
