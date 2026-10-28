import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PublicMobileNav from '@/components/PublicMobileNav';

const links = [
    { href: '/metodologia', label: 'Metodología' },
    { href: '/ayuda', label: 'Ayuda' },
];

beforeEach(() => {
    // jsdom no implementa matchMedia.
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
        matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
});

describe('PublicMobileNav', () => {
    it('abre el drawer en portal con los enlaces y aria-expanded sincronizado', () => {
        render(<PublicMobileNav links={links} />);
        const trigger = screen.getByRole('button', { name: 'Abrir menú de páginas' });
        expect(trigger).toHaveAttribute('aria-expanded', 'false');
        fireEvent.click(trigger);
        expect(trigger).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByRole('dialog', { name: 'Menú de páginas' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Metodología' })).toBeInTheDocument();
    });

    it('bloquea el scroll del body mientras está abierto y lo restaura al cerrar', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        expect(document.body.style.overflow).toBe('hidden');
        fireEvent.click(screen.getByRole('button', { name: 'Cerrar menú de páginas' }));
        expect(document.body.style.overflow).toBe('');
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('Escape cierra el menú', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('el backdrop cierra sin ser un tab stop', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        const backdrop = screen.getByRole('button', { name: 'Cerrar menú por fondo' });
        expect(backdrop).toHaveAttribute('tabindex', '-1');
        fireEvent.click(backdrop);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('navegar con un enlace cierra el drawer', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        fireEvent.click(screen.getByRole('link', { name: 'Ayuda' }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('la CTA viaja al drawer y también cierra', () => {
        render(<PublicMobileNav links={links} cta={{ href: '/sign-up', label: 'Crear cuenta' }} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        const cta = screen.getByRole('link', { name: 'Crear cuenta' });
        expect(cta).toBeInTheDocument();
        fireEvent.click(cta);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('el foco entra por el botón de cerrar', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cerrar menú de páginas' }));
    });
});

describe('PublicMobileNav (trampas de foco y breakpoints)', () => {
    function stubMatchMedia(matches = false) {
        const listeners: Record<string, EventListener[]> = {};
        vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
            matches, media: query,
            addEventListener: (ev: string, cb: EventListener) => { (listeners[ev] ??= []).push(cb); },
            removeEventListener: vi.fn(),
        })));
        return listeners;
    }

    it('el ciclo Tab vuelve del último focuseable al primero y Shift+Tab al revés', () => {
        stubMatchMedia();
        vi.spyOn(Element.prototype, 'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        const dialog = screen.getByRole('dialog', { name: 'Menú de páginas' });
        const focusables = Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]'))
            .filter((el) => el.tabIndex >= 0);
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        last.focus();
        fireEvent.keyDown(document, { key: 'Tab' });
        expect(document.activeElement).toBe(first);
        first.focus();
        fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
        expect(document.activeElement).toBe(last);
        vi.restoreAllMocks();
    });

    it('Tab sin focuseables visibles deja el foco en el diálogo', () => {
        stubMatchMedia();
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        fireEvent.keyDown(document, { key: 'Tab' });
        expect(document.activeElement).toBe(screen.getByRole('dialog', { name: 'Menú de páginas' }));
    });

    it('cruzar a md+ con el drawer abierto lo cierra', () => {
        const listeners = stubMatchMedia(true);
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        act(() => { for (const cb of listeners['change'] ?? []) cb(new Event('change')); });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
});
