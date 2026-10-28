import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Skeleton } from '@/components/ui/skeleton';
import { MethodologyDisclosure } from '@/components/ui/methodology-disclosure';
import { Pagination, PagedList } from '@/components/ui/pagination';
import { Slider } from '@/components/ui/slider';
import { NameAvatar } from '@/components/ui/name-avatar';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';

describe('Skeleton', () => {
    it('renderiza el placeholder con animate-pulse y acepta clases extra', () => {
        const { container } = render(<Skeleton className="h-4" data-testid="sk" />);
        expect(screen.getByTestId('sk')).toHaveClass('animate-pulse', 'h-4');
        expect(container.firstChild).toBeInTheDocument();
    });
});

describe('MethodologyDisclosure', () => {
    it('usa <details> nativo cerrado por defecto con el título estándar', () => {
        render(<MethodologyDisclosure>Contenido metodológico</MethodologyDisclosure>);
        const details = screen.getByText('Metodología y límites').closest('details')!;
        expect(details).not.toHaveAttribute('open');
        expect(screen.getByText('Contenido metodológico')).toBeInTheDocument();
    });
    it('acepta un título propio', () => {
        render(<MethodologyDisclosure title="Cómo se calcula">x</MethodologyDisclosure>);
        expect(screen.getByText('Cómo se calcula')).toBeInTheDocument();
    });
});

describe('Pagination', () => {
    it('con una sola página no muestra controles', () => {
        const { container } = render(<Pagination page={1} pages={1} onPageChange={vi.fn()} label="Historial" />);
        expect(container).toBeEmptyDOMElement();
    });
    it('deshabilita Anterior en la primera página y Siguiente en la última', () => {
        render(<Pagination page={1} pages={3} onPageChange={vi.fn()} label="Historial" />);
        expect(screen.getByRole('button', { name: 'Página anterior: Historial' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Página siguiente: Historial' })).toBeEnabled();
        expect(screen.getByText('Página 1 de 3')).toHaveAttribute('aria-current', 'page');
    });
    it('fuera de rango queda fijado (clamp) en vez de paginar a un hueco', () => {
        const onPageChange = vi.fn();
        render(<Pagination page={99} pages={3} onPageChange={onPageChange} label="Historial" />);
        expect(screen.getByText('Página 3 de 3')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Página anterior: Historial' }));
        expect(onPageChange).toHaveBeenCalledWith(2); // 3-1, no 98
    });
    it('navega con Anterior/Siguiente', () => {
        const onPageChange = vi.fn();
        render(<Pagination page={2} pages={3} onPageChange={onPageChange} label="Historial" />);
        fireEvent.click(screen.getByRole('button', { name: 'Página siguiente: Historial' }));
        expect(onPageChange).toHaveBeenCalledWith(3);
    });
});

describe('PagedList', () => {
    const items = Array.from({ length: 25 }, (_, i) => ({ key: `k${i}`, node: <span>Fila {i}</span> }));
    it('muestra 10 por página y cambia de página', () => {
        render(<PagedList items={items} label="Operaciones" />);
        expect(screen.getByText('Fila 0')).toBeInTheDocument();
        expect(screen.queryByText('Fila 10')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Página siguiente: Operaciones' }));
        expect(screen.queryByText('Fila 0')).not.toBeInTheDocument();
        expect(screen.getByText('Fila 10')).toBeInTheDocument();
    });
});

describe('Slider', () => {
    it('el aria-label va en el thumb (role slider), no en el contenedor', () => {
        render(<Slider aria-label="Importe mínimo" defaultValue={[50]} />);
        expect(screen.getByRole('slider', { name: 'Importe mínimo' })).toHaveAttribute('aria-valuenow', '50');
    });
});

describe('NameAvatar', () => {
    it('sin foto pinta iniciales ocultas a lectores de pantalla', () => {
        const { container } = render(<NameAvatar name="Warren Buffett" />);
        const span = container.querySelector('span[aria-hidden="true"]')!;
        expect(span).toBeInTheDocument();
        expect(span.textContent?.length).toBeGreaterThan(0);
    });
    it('con foto muestra la imagen con alt de la persona', () => {
        render(<NameAvatar name="Warren Buffett" photoSrc="/buffett.jpg" photoTitle="Foto de Warren Buffett" />);
        expect(screen.getByAltText('Foto de Warren Buffett')).toBeInTheDocument();
    });
});

describe('Avatar', () => {
    it('muestra la imagen cuando carga correctamente', async () => {
        // Radix Avatar crea un Image para sondear la carga; se simula éxito.
        const Original = window.Image;
        class FakeImage {
            complete = false;
            naturalWidth = 0;
            private listeners: Record<string, Array<(e: unknown) => void>> = {};
            addEventListener(ev: string, cb: (e: unknown) => void) { (this.listeners[ev] ??= []).push(cb); }
            removeEventListener() { /* sin-op */ }
            set src(_v: string) {
                this.complete = true;
                this.naturalWidth = 1;
                queueMicrotask(() => (this.listeners['load'] ?? []).forEach((cb) => cb({ currentTarget: this })));
            }
        }
        vi.stubGlobal('Image', FakeImage);
        render(<Avatar><AvatarImage src="/nico.png" alt="Nico" /><AvatarFallback>NI</AvatarFallback></Avatar>);
        await screen.findByRole('img', { name: 'Nico' });
        vi.stubGlobal('Image', Original);
    });
    it('muestra el fallback cuando no hay imagen cargada', () => {
        render(<Avatar><AvatarFallback>NI</AvatarFallback></Avatar>);
        expect(screen.getByText('NI')).toBeInTheDocument();
    });
});
