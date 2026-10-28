import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
    usePathname: () => '/inicio',
    useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: vi.fn(async () => []),
    getPopularStocks: vi.fn(async () => []),
}));
vi.mock('@/lib/popular-stocks-loader', () => ({ loadPopularStocks: vi.fn(async () => []) }));

import MobileNav from '@/components/MobileNav';

beforeEach(() => {
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
        matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
});

describe('MobileNav', () => {
    it('el hamburger abre el drawer con el MISMO árbol que el sidebar', () => {
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        expect(screen.getByRole('dialog', { name: 'Menú de navegación' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Cartera' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Biblioteca' })).toBeInTheDocument();
    });
    it('Escape cierra y el scroll del body se restaura', () => {
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        expect(document.body.style.overflow).toBe('hidden');
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(document.body.style.overflow).toBe('');
    });
    it('el botón de cerrar recibe el foco al abrir', () => {
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cerrar menú de navegación' }));
    });
    it('cerrar por el fondo no deja el diálogo montado', () => {
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        fireEvent.click(screen.getByRole('button', { name: 'Cerrar menú por fondo' }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
});

describe('MobileNav (trampas de foco y breakpoints)', () => {
    function stubMatchMedia(matches = false) {
        const listeners: Record<string, EventListener[]> = {};
        vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
            matches, media: query,
            addEventListener: (ev: string, cb: EventListener) => { (listeners[ev] ??= []).push(cb); },
            removeEventListener: vi.fn(),
        })));
        return listeners;
    }

    it('el botón Cerebro cierra el drawer y emite gerarai:open-brain', () => {
        const onBrain = vi.fn();
        window.addEventListener('gerarai:open-brain', onBrain);
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        fireEvent.click(screen.getByRole('button', { name: /Cerebro/ }));
        expect(onBrain).toHaveBeenCalledTimes(1);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        window.removeEventListener('gerarai:open-brain', onBrain);
    });

    it('pulsar un enlace del árbol cierra el drawer', () => {
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        fireEvent.click(screen.getByRole('link', { name: 'Cartera' }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(document.body.style.overflow).toBe('');
    });

    it('el ciclo Tab vuelve del último focuseable al primero y Shift+Tab al revés', () => {
        stubMatchMedia();
        // jsdom no layouta: sin rectángulos el filtro deja la lista vacía.
        vi.spyOn(Element.prototype, 'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        const dialog = screen.getByRole('dialog', { name: 'Menú de navegación' });
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
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        fireEvent.keyDown(document, { key: 'Tab' });
        expect(document.activeElement).toBe(screen.getByRole('dialog', { name: 'Menú de navegación' }));
    });

    it('cruzar a md+ con el drawer abierto lo cierra', () => {
        const listeners = stubMatchMedia(true);
        render(<MobileNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        act(() => { for (const cb of listeners['change'] ?? []) cb(new Event('change')); });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
});
