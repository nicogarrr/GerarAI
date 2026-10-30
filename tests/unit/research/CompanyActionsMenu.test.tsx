import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanyActionsMenu from '@/components/research/CompanyActionsMenu';

describe('Company secondary actions navigation', () => {
    it.each([0, 3])('opens only on request, labels changes count %s and escapes route/query ticker', async changeCount => {
        render(<CompanyActionsMenu ticker="A/B & C" changeCount={changeCount} />);
        const trigger = screen.getByRole('button', { name: 'Más acciones' });
        expect(trigger).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
        fireEvent.click(trigger);
        const nav = await screen.findByRole('navigation', { name: 'Enlaces de la empresa' });
        expect(trigger).toHaveAttribute('aria-expanded', 'true');
        const links = [
            [changeCount ? 'Qué ha cambiado (3)' : 'Qué ha cambiado', '/research/A%2FB%20%26%20C?view=seguimiento'],
            ['Diario de decisiones', '/research/A%2FB%20%26%20C?view=seguimiento#diario-decisiones'],
            ['Terminal financiero', '/research/A%2FB%20%26%20C?view=finanzas#terminal'],
            ['Supuestos de drivers', '/research/A%2FB%20%26%20C?view=valoracion#supuestos'],
            ['Lecciones de decisiones', '/research/A%2FB%20%26%20C?view=seguimiento#lecciones'],
            ['Credibilidad de la directiva', '/research/A%2FB%20%26%20C?view=seguimiento#directiva'],
            ['Dilución y recompras', '/research/A%2FB%20%26%20C?view=finanzas#dilucion'],
            ['Cortos públicos', '/research/A%2FB%20%26%20C/shorts'],
            ['Noticias', '/research/news?ticker=A%2FB%20%26%20C'],
            ['Insiders', '/insider?ticker=A%2FB%20%26%20C'],
            ['Dividendos y splits', '/corporate-actions?ticker=A%2FB%20%26%20C'],
        ];
        for (const [name, href] of links) expect(within(nav).getByRole('link', { name })).toHaveAttribute('href', href);
        expect(within(nav).getAllByRole('link')).toHaveLength(11);
        expect(within(nav).getByRole('button', { name: 'Guía de investigación' })).toBeVisible();
        fireEvent.keyDown(nav, { key: 'Escape' });
        expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
        expect(trigger).toHaveAttribute('aria-expanded', 'false');
    });
    it('opens the research guide with the current ticker without changing accounts or creating work', async () => {
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        try {
            render(<CompanyActionsMenu ticker="BRK.B" changeCount={0} />);
            fireEvent.click(screen.getByRole('button', { name: 'Más acciones' }));
            fireEvent.click(await screen.findByRole('button', { name: 'Guía de investigación' }));
            expect(listener).toHaveBeenCalledOnce();
            const event = listener.mock.calls[0][0] as CustomEvent;
            expect(event.detail).toEqual({ ticker: 'BRK.B' });
        } finally {
            window.removeEventListener('gerarai:open-brain', listener);
        }
    });
});
