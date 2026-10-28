import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Inbox } from 'lucide-react';

beforeEach(() => {
    // Panel consulta el breakpoint para el modo plegable móvil.
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
        matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
});

import { PageHeader } from '@/components/ui/page-header';
import { Stat } from '@/components/ui/stat';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import MobileCollapse from '@/components/ui/mobile-collapse';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Panel } from '@/components/ui/panel';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCaption, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';

describe('PageHeader', () => {
    it('pinta kicker, h1, descripción, volver, acciones y contenido extra', () => {
        render(
            <PageHeader kicker="Research" title="Apple" description="Análisis profundo"
                back={<button>Volver</button>} actions={<button>Exportar</button>}>
                <div>Pestañas</div>
            </PageHeader>,
        );
        expect(screen.getByRole('heading', { level: 1, name: 'Apple' })).toBeInTheDocument();
        expect(screen.getByText('Research')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Volver' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Exportar' })).toBeInTheDocument();
    });
    it('sin accesorios solo pinta el título', () => {
        render(<PageHeader title="Cartera" />);
        expect(screen.getByRole('heading', { level: 1, name: 'Cartera' })).toBeInTheDocument();
    });
});

describe('Stat', () => {
    it('aplica tono y tamaño al dato, y muestra el hint', () => {
        const { container } = render(<Stat label="Rentabilidad" value="+12,3 %" tone="good" size="sm" hint="YTD" />);
        expect(screen.getByText('Rentabilidad')).toBeInTheDocument();
        expect(screen.getByText('YTD')).toBeInTheDocument();
        expect(container.querySelector('.text-good')).toBeInTheDocument();
    });
    it('el tono negativo usa el token bad', () => {
        const { container } = render(<Stat label="Pérdida" value="-5 %" tone="bad" />);
        expect(container.querySelector('.text-bad')).toBeInTheDocument();
    });
});

describe('Tabs', () => {
    it('cambia de panel al pulsar otra pestaña', () => {
        render(
            <Tabs defaultValue="resumen">
                <TabsList>
                    <TabsTrigger value="resumen">Resumen</TabsTrigger>
                    <TabsTrigger value="datos">Datos</TabsTrigger>
                </TabsList>
                <TabsContent value="resumen">Panel resumen</TabsContent>
                <TabsContent value="datos">Panel datos</TabsContent>
            </Tabs>,
        );
        expect(screen.getByText('Panel resumen')).toBeInTheDocument();
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'Datos' }));
        fireEvent.click(screen.getByRole('tab', { name: 'Datos' }));
        expect(screen.getByText('Panel datos')).toBeInTheDocument();
        expect(screen.queryByText('Panel resumen')).not.toBeInTheDocument();
    });
});

describe('MobileCollapse', () => {
    it('empieza plegado y alterna aria-expanded al pulsar', () => {
        render(<MobileCollapse title="Detalles"><div>Contenido colapsable</div></MobileCollapse>);
        const btn = screen.getByRole('button', { name: /Detalles/ });
        expect(btn).toHaveAttribute('aria-expanded', 'false');
        fireEvent.click(btn);
        expect(btn).toHaveAttribute('aria-expanded', 'true');
        fireEvent.click(btn);
        expect(btn).toHaveAttribute('aria-expanded', 'false');
    });
});

describe('EmptyState', () => {
    it('pinta icono, título como h1, descripción y acción', () => {
        render(
            <EmptyState icon={Inbox} titleAs="h1" title="Sin resultados" description="Prueba otros filtros"
                action={<button>Reintentar</button>} />,
        );
        expect(screen.getByRole('heading', { level: 1, name: 'Sin resultados' })).toBeInTheDocument();
        expect(screen.getByText('Prueba otros filtros')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument();
    });
    it('EmptyLink enlaza al primer paso', () => {
        render(<EmptyLink href="/importar">Importar cartera</EmptyLink>);
        expect(screen.getByRole('link', { name: 'Importar cartera' })).toHaveAttribute('href', '/importar');
    });
});

describe('ConfirmDialog', () => {
    it('confirmar ejecuta la acción y cierra; cancelar solo cierra', () => {
        const onConfirm = vi.fn();
        const onOpenChange = vi.fn();
        render(
            <ConfirmDialog open onOpenChange={onOpenChange} title="Eliminar posición"
                description="Esta acción no se puede deshacer" onConfirm={onConfirm} />,
        );
        expect(screen.getByRole('dialog', { name: 'Eliminar posición' })).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
        expect(onOpenChange).toHaveBeenCalledWith(false);
        expect(onConfirm).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        expect(onConfirm).toHaveBeenCalledTimes(1);
    });
});

describe('Popover', () => {
    it('abre el contenido flotante al pulsar el trigger', async () => {
        render(
            <Popover>
                <PopoverTrigger>Ver detalle</PopoverTrigger>
                <PopoverContent>Texto del popover</PopoverContent>
            </Popover>,
        );
        fireEvent.click(screen.getByRole('button', { name: 'Ver detalle' }));
        expect(await screen.findByText('Texto del popover')).toBeInTheDocument();
    });
});

describe('Dialog', () => {
    it('abre con el trigger y muestra título y descripción', async () => {
        render(
            <Dialog>
                <DialogTrigger>Abrir ficha</DialogTrigger>
                <DialogContent>
                    <DialogTitle>Ficha</DialogTitle>
                    <DialogDescription>Detalle del activo</DialogDescription>
                </DialogContent>
            </Dialog>,
        );
        fireEvent.click(screen.getByRole('button', { name: 'Abrir ficha' }));
        expect(await screen.findByRole('dialog', { name: 'Ficha' })).toBeInTheDocument();
        expect(screen.getByText('Detalle del activo')).toBeInTheDocument();
    });
});

describe('Panel', () => {
    it('pinta título y contenido', () => {
        render(<Panel title="Resumen"><p>Cuerpo del panel</p></Panel>);
        expect(screen.getByText('Resumen')).toBeInTheDocument();
        expect(screen.getByText('Cuerpo del panel')).toBeInTheDocument();
    });
});

describe('Select', () => {
    it('lista opciones y refleja la elegida', async () => {
        render(
            <Select defaultValue="eur">
                <SelectTrigger aria-label="Moneda"><SelectValue /></SelectTrigger>
                <SelectContent>
                    <SelectItem value="eur">EUR</SelectItem>
                    <SelectItem value="usd">USD</SelectItem>
                </SelectContent>
            </Select>,
        );
        expect(screen.getByRole('combobox', { name: 'Moneda' })).toHaveTextContent('EUR');
        fireEvent.keyDown(screen.getByRole('combobox', { name: 'Moneda' }), { key: 'Enter' });
        const usd = await screen.findByRole('option', { name: 'USD' });
        fireEvent.click(usd);
        expect(screen.getByRole('combobox', { name: 'Moneda' })).toHaveTextContent('USD');
    });
});

describe('Table', () => {
    it('estructura caption, cabecera, cuerpo y pie accesibles', () => {
        render(
            <Table>
                <TableCaption>Movimientos del trimestre</TableCaption>
                <TableHeader>
                    <TableRow><TableHead>Fecha</TableHead><TableHead>Importe</TableHead></TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow><TableCell>01/10/2026</TableCell><TableCell>-100 €</TableCell></TableRow>
                </TableBody>
                <TableFooter>
                    <TableRow><TableCell>Total</TableCell><TableCell>-100 €</TableCell></TableRow>
                </TableFooter>
            </Table>,
        );
        expect(screen.getByRole('table', { name: 'Movimientos del trimestre' })).toBeInTheDocument();
        expect(screen.getByRole('columnheader', { name: 'Importe' })).toBeInTheDocument();
        expect(screen.getAllByRole('cell', { name: '-100 €' })).toHaveLength(2);
        expect(screen.getAllByRole('row')).toHaveLength(3);
    });

    it('la región con scroll horizontal anuncia que hay más columnas', () => {
        // F176: las tablas anchas comparten la affordance (scrollbar fina
        // visible + sombras de borde); sin ella el borde de scroll corta el
        // contenido a media palabra sin pista de que hay más a la derecha.
        render(
            <Table regionLabel="Posiciones de la cartera">
                <TableBody>
                    <TableRow><TableCell>AAPL</TableCell></TableRow>
                </TableBody>
            </Table>,
        );
        const region = screen.getByRole('region', { name: 'Posiciones de la cartera' });
        expect(region.className).toContain('scroll-affordance-x');
        expect(region.className).toContain('overflow-x-auto');
        expect(region).toHaveAttribute('tabIndex', '0');
    });
});
