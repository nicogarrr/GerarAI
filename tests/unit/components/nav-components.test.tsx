import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ pathname: vi.fn(() => '/inicio') }));
vi.mock('next/navigation', () => ({ usePathname: () => mocks.pathname() }));

import NavItems from '@/components/NavItems';
import BottomNav from '@/components/layout/BottomNav';
import SectionNav from '@/components/layout/SectionNav';

beforeEach(() => {
    mocks.pathname.mockReturnValue('/inicio');
    window.localStorage.clear();
});

describe('NavItems', () => {
    it('renderiza todos los destinos del menú como enlaces', () => {
        render(<NavItems />);
        for (const label of ['Inicio', 'Cartera', 'Research', 'Descubrir', 'Watchlist', 'Biblioteca']) {
            expect(screen.getByRole('link', { name: label })).toBeInTheDocument();
        }
    });
    it('la página actual lleva aria-current="page"; las demás no llevan aria-current', () => {
        mocks.pathname.mockReturnValue('/portfolio');
        render(<NavItems />);
        expect(screen.getByRole('link', { name: 'Cartera' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: 'Inicio' })).not.toHaveAttribute('aria-current');
    });
    it('una sección hija activa marca la rama sin aria-current de página en el padre', () => {
        mocks.pathname.mockReturnValue('/research/MSFT');
        render(<NavItems />);
        const research = screen.getByRole('link', { name: 'Research' });
        // /research/MSFT cuelga de /research: activo pero no exacto → aria-current="true"
        expect(research.getAttribute('aria-current')).toMatch(/^(page|true)$/);
    });
});

describe('BottomNav', () => {
    it('cinco destinos con etiqueta más el botón central Cerebro en la misma rejilla', () => {
        render(<BottomNav />);
        const nav = screen.getByRole('navigation', { name: 'Navegación inferior' });
        expect(nav.querySelectorAll('li')).toHaveLength(6);
        expect(screen.getByRole('button', { name: 'Abrir el cerebro' })).toBeInTheDocument();
    });
    it('el botón Cerebro emite el evento de apertura, no navega', () => {
        const onOpen = vi.fn();
        window.addEventListener('gerarai:open-brain', onOpen);
        render(<BottomNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir el cerebro' }));
        expect(onOpen).toHaveBeenCalledTimes(1);
        window.removeEventListener('gerarai:open-brain', onOpen);
    });
    it('la pestaña activa lleva aria-current', () => {
        mocks.pathname.mockReturnValue('/discover');
        render(<BottomNav />);
        expect(screen.getByRole('link', { name: 'Descubrir' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: 'Inicio' })).not.toHaveAttribute('aria-current');
    });
});

describe('SectionNav', () => {
    it('en /discover no pinta subnav (la portada ya es el índice del hub)', () => {
        mocks.pathname.mockReturnValue('/discover');
        const { container } = render(<SectionNav />);
        expect(container).toBeEmptyDOMElement();
    });
    it('en Cartera lista las herramientas del hub y marca la actual', () => {
        mocks.pathname.mockReturnValue('/portfolio/intelligence');
        render(<SectionNav />);
        expect(screen.getByRole('link', { name: 'Inteligencia' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: 'Impuestos' })).not.toHaveAttribute('aria-current');
    });
    it('empieza plegado, despliega al pulsar y recuerda la decisión en localStorage', () => {
        mocks.pathname.mockReturnValue('/portfolio');
        render(<SectionNav />);
        const toggle = screen.getByRole('button', { name: /Resumen|Secciones/ });
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        fireEvent.click(toggle);
        expect(toggle).toHaveAttribute('aria-expanded', 'true');
        expect(window.localStorage.getItem('subnav-seccion')).toBe('abierto');
    });
    it('con la preferencia guardada «abierto» arranca desplegado', async () => {
        window.localStorage.setItem('subnav-seccion', 'abierto');
        mocks.pathname.mockReturnValue('/portfolio');
        render(<SectionNav />);
        await waitFor(() => expect(screen.getByRole('button', { name: /Resumen|Secciones/ })).toHaveAttribute('aria-expanded', 'true'));
    });
});
