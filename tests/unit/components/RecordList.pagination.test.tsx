import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RecordList, type DataRecord } from '@/components/data/RecordViews';

// El paginador separa «Página x de y» en su propio span (NBSP/huérfanos 390px):
// hay que casar por textContent normalizado, no por texto plano.
const byTextContent = (text: string) => (_: string, el?: Element | null) =>
    (el?.textContent ?? '').replace(/\s+/g, ' ').trim() === text;

const records = (n: number): DataRecord[] =>
    Array.from({ length: n }, (_, i) => ({ id: i + 1, ticker: `T${String(i + 1).padStart(2, '0')}` }));

describe('RecordList paginación', () => {
    it('sin pageSize pinta todas las filas y sin paginador', () => {
        render(<RecordList fetchRecords={async () => []} records={records(30)} title="Prueba" />);
        expect(screen.getAllByText('T30').length).toBeGreaterThan(0);
        expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    });
    it('con pageSize muestra una página y paginador arriba y abajo', () => {
        render(<RecordList fetchRecords={async () => []} pageSize={10} records={records(30)} title="Prueba" />);
        expect(screen.getAllByText('T10').length).toBeGreaterThan(0);
        expect(screen.queryByText('T11')).not.toBeInTheDocument();
        const pagers = screen.getAllByRole('navigation', { name: 'Paginación de registros' });
        expect(pagers).toHaveLength(2);
        expect(screen.getAllByText(byTextContent('Página 1 de 3 · 30 registros'))).toHaveLength(2);
    });
    it('cambiar de página muestra las filas siguientes', () => {
        render(<RecordList fetchRecords={async () => []} pageSize={10} records={records(30)} title="Prueba" />);
        fireEvent.click(screen.getAllByRole('button', { name: 'Siguiente' })[0]);
        expect(screen.queryByText('T10')).not.toBeInTheDocument();
        expect(screen.getAllByText('T11').length).toBeGreaterThan(0);
    });
    it('una acción de fila en página 2 parchea la fila correcta', () => {
        render(
            <RecordList
                columns={['ticker', 'applied']}
                fetchRecords={async () => []}
                pageSize={10}
                records={records(12)}
                rowActions={(record, _index, replace) => (
                    <button type="button" onClick={() => replace({ applied: 'sí' })}>Aplicar {String(record.ticker)}</button>
                )}
                title="Prueba"
            />,
        );
        fireEvent.click(screen.getAllByRole('button', { name: 'Siguiente' })[0]);
        fireEvent.click(screen.getAllByRole('button', { name: 'Aplicar T12' })[0]);
        // T12 queda marcada y T11 no se toca.
        const t12 = screen.getAllByText('T12')[0].closest('tr') ?? screen.getAllByText('T12')[0].closest('li');
        expect(t12?.textContent).toContain('sí');
        const t11 = screen.getAllByText('T11')[0].closest('tr') ?? screen.getAllByText('T11')[0].closest('li');
        expect(t11?.textContent).not.toContain('sí');
    });
});
