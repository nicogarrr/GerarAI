import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

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
});
