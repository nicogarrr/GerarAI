import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import {
    DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuGroup,
    DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
    DropdownMenuSeparator, DropdownMenuShortcut, DropdownMenuSub, DropdownMenuSubContent,
    DropdownMenuSubTrigger, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Toaster } from '@/components/ui/sonner';

describe('Command (paleta)', () => {
    it('muestra el título accesible, filtra por texto y avisa cuando no hay resultados', async () => {
        render(
            <CommandDialog open>
                <CommandInput placeholder="Buscar…" />
                <CommandList>
                    <CommandEmpty>Nada encontrado</CommandEmpty>
                    <CommandGroup heading="Secciones">
                        <CommandItem value="cartera">Cartera</CommandItem>
                        <CommandItem value="alertas">Alertas</CommandItem>
                    </CommandGroup>
                </CommandList>
            </CommandDialog>,
        );
        expect(screen.getByRole('dialog', { name: 'Paleta de comandos' })).toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('Buscar…'), { target: { value: 'cart' } });
        await waitFor(() => expect(screen.getByText('Cartera')).toBeInTheDocument());
        expect(screen.queryByText('Alertas')).not.toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('Buscar…'), { target: { value: 'zzzz' } });
        await waitFor(() => expect(screen.getByText('Nada encontrado')).toBeInTheDocument());
    });
});

describe('DropdownMenu', () => {
    it('abre con el trigger y ejecuta la acción elegida', async () => {
        const onSelect = vi.fn();
        render(
            <DropdownMenu>
                <DropdownMenuTrigger>Abrir acciones</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <DropdownMenuLabel>Operaciones</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onSelect={onSelect}>Duplicar</DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>,
        );
        const trigger = screen.getByRole('button', { name: 'Abrir acciones' });
        fireEvent.keyDown(trigger, { key: 'Enter' });
        const item = await screen.findByRole('menuitem', { name: 'Duplicar' });
        expect(screen.getByText('Operaciones')).toBeInTheDocument();
        fireEvent.click(item);
        expect(onSelect).toHaveBeenCalledTimes(1);
    });
});

describe('Toaster', () => {
    it('monta el landmark accesible de notificaciones con atajo anunciado', () => {
        render(<Toaster />);
        expect(screen.getByLabelText('Notifications alt+T')).toBeInTheDocument();
    });
});

describe('DropdownMenu (variantes del wrapper)', () => {
    it('checkbox, radio, grupo, atajo y submenú renderizan y responden', async () => {
        const onCheck = vi.fn();
        const onRadio = vi.fn();
        render(
            <DropdownMenu>
                <DropdownMenuTrigger>Más acciones</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <DropdownMenuGroup>
                        <DropdownMenuCheckboxItem checked onCheckedChange={onCheck}>
                            Visible
                        </DropdownMenuCheckboxItem>
                    </DropdownMenuGroup>
                    <DropdownMenuRadioGroup value="eur" onValueChange={onRadio}>
                        <DropdownMenuRadioItem value="eur">EUR</DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="usd">USD</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                    <DropdownMenuItem>
                        Guardar
                        <DropdownMenuShortcut>⌘S</DropdownMenuShortcut>
                    </DropdownMenuItem>
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger>Exportar</DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuItem>CSV</DropdownMenuItem>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </DropdownMenuContent>
            </DropdownMenu>,
        );
        const trigger = screen.getByRole('button', { name: 'Más acciones' });
        fireEvent.keyDown(trigger, { key: 'Enter' });
        const checkbox = await screen.findByRole('menuitemcheckbox', { name: 'Visible' });
        expect(checkbox).toHaveAttribute('aria-checked', 'true');
        expect(screen.getByRole('menuitemradio', { name: 'EUR' })).toHaveAttribute('aria-checked', 'true');
        expect(screen.getByText('⌘S')).toBeInTheDocument();
        // Radix cierra el menú al seleccionar: se reabre entre interacciones.
        fireEvent.click(checkbox);
        expect(onCheck).toHaveBeenCalledWith(false);
        fireEvent.keyDown(trigger, { key: 'Enter' });
        fireEvent.click(await screen.findByRole('menuitemradio', { name: 'USD' }));
        expect(onRadio).toHaveBeenCalledWith('usd');
        fireEvent.keyDown(trigger, { key: 'Enter' });
        const subTrigger = await screen.findByRole('menuitem', { name: 'Exportar' });
        fireEvent.keyDown(subTrigger, { key: 'ArrowRight' });
        await waitFor(() => expect(screen.getByRole('menuitem', { name: 'CSV' })).toBeInTheDocument());
    });
});
