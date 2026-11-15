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
        expect(screen.getByRole('dialog', { name: 'Menú de páginas' }).tagName).toBe('DIALOG');
        expect(screen.getByRole('link', { name: 'Metodología' })).toBeInTheDocument();
    });

    it('no modifica el scroll del body al abrir ni al cerrar', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        expect(document.body.style.overflow).toBe('');
        fireEvent.click(screen.getByRole('button', { name: 'Cerrar menú de páginas' }));
        expect(document.body.style.overflow).toBe('');
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('Escape cierra el menú', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        // jsdom has no native Escape default; browser test presses the key.
        act(() => { (screen.getByRole('dialog') as HTMLDialogElement).close(); });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('el backdrop nativo no crea un tab stop y el fallback despide fuera del panel', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        const dialog = screen.getByRole('dialog');
        expect(dialog).toHaveAttribute('closedby', 'any');
        expect(screen.queryByRole('button', { name: 'Cerrar menú por fondo' })).toBeNull();
        vi.spyOn(dialog, 'getBoundingClientRect').mockReturnValue({ left: 90, right: 390, top: 0, bottom: 844 } as DOMRect);
        fireEvent(dialog, new MouseEvent('pointerdown', { clientX: 40, clientY: 400 }));
        fireEvent(dialog, new MouseEvent('pointerup', { clientX: 40, clientY: 400 }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('pulsar el fondo interior del nav no cierra el menú', () => {
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        fireEvent.click(screen.getByRole('navigation', { name: 'Páginas de GerarAI' }));
        expect(screen.getByRole('dialog')).toBeInTheDocument();
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

    it('conserva el modal y el foco al actualizar enlaces mientras está abierto', () => {
        const { rerender } = render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        const link = screen.getByRole('link', { name: 'Ayuda' });
        link.focus();
        rerender(<PublicMobileNav links={[...links, { href: '/legal', label: 'Legal' }]} />);
        expect(document.activeElement).toBe(link);
        expect((screen.getByRole('dialog') as HTMLDialogElement).open).toBe(true);
    });

    it('cruzar a md+ con el drawer abierto lo cierra', () => {
        const listeners = stubMatchMedia(false);
        render(<PublicMobileNav links={links} />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de páginas' }));
        vi.mocked(window.matchMedia).mock.results[0].value.matches = true;
        act(() => { for (const cb of listeners['change'] ?? []) cb(new Event('change')); });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
});
