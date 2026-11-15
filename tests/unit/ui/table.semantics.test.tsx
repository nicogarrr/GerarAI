import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';

// Las tablas responsivas del repo cambian display (block md:table, filas de
// tarjeta en móvil). Medido 2024 (zellwk.com, matriz navegador × lector):
// con display alterado, VoiceOver + Safari anuncia la tabla SIN filas ni
// columnas; los roles explícitos las restauran. Pin: cada elemento del
// componente compartido lleva su role ARIA aunque el display cambie.
describe('semántica de tabla explícita (display responsivo)', () => {
    it('table, rowgroups, rows y celdas llevan role aunque cambie el display', () => {
        const { container } = render(
            <Table className="block md:table">
                <TableHeader className="hidden md:table-header-group">
                    <TableRow className="block md:table-row">
                        <TableHead>Ticker</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody className="block md:table-row-group">
                    <TableRow className="block md:table-row">
                        <TableCell className="block md:table-cell">ASTS</TableCell>
                    </TableRow>
                </TableBody>
            </Table>,
        );
        expect(container.querySelector('table')).toHaveAttribute('role', 'table');
        expect(container.querySelector('thead')).toHaveAttribute('role', 'rowgroup');
        expect(container.querySelector('tbody')).toHaveAttribute('role', 'rowgroup');
        for (const row of container.querySelectorAll('tr')) {
            expect(row).toHaveAttribute('role', 'row');
        }
        expect(container.querySelector('th')).toHaveAttribute('role', 'columnheader');
        expect(container.querySelector('th')).toHaveAttribute('scope', 'col');
        expect(container.querySelector('td')).toHaveAttribute('role', 'cell');
    });

    it('TableHead deriva role de scope: fila -> rowheader, columna -> columnheader', () => {
        // <th scope="row|rowgroup"> es cabecera de FILA (rowheader); fijar
        // role="columnheader" lo anunciaría mal aunque el scope diga lo
        // contrario (auditor1, 2026-11-14).
        const { container } = render(
            <Table>
                <TableBody>
                    <TableRow>
                        <TableHead scope="row">Total cartera</TableHead>
                        <TableCell>100.000</TableCell>
                    </TableRow>
                    <TableRow>
                        <TableHead scope="rowgroup">Renta variable</TableHead>
                        <TableCell>60.000</TableCell>
                    </TableRow>
                    <TableRow>
                        <TableHead scope="colgroup">Renta fija</TableHead>
                        <TableCell>40.000</TableCell>
                    </TableRow>
                </TableBody>
            </Table>,
        );
        const heads = container.querySelectorAll('th');
        expect(heads[0]).toHaveAttribute('role', 'rowheader');
        expect(heads[1]).toHaveAttribute('role', 'rowheader');
        expect(heads[2]).toHaveAttribute('role', 'columnheader');
    });

    it('TableFooter también lleva role=rowgroup (mismo riesgo de display CSS)', () => {
        const { container } = render(
            <Table>
                <TableFooter className="block">
                    <TableRow>
                        <TableCell>Total</TableCell>
                    </TableRow>
                </TableFooter>
            </Table>,
        );
        expect(container.querySelector('tfoot')).toHaveAttribute('role', 'rowgroup');
    });
});
