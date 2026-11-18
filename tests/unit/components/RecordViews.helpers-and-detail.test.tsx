import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
    RecordDetail,
    RecordList,
    formatRecordValue,
    pickColumns,
    researchHrefFor,
    toRecords,
} from '@/components/data/RecordViews';

const toast = vi.hoisted(() => ({ showErrorToast: vi.fn() }));
vi.mock('@/lib/toast', () => ({ showErrorToast: toast.showErrorToast }));

beforeEach(() => {
    toast.showErrorToast.mockReset();
});

afterEach(() => {
    // @ts-expect-error limpiar el mock de matchMedia, si algun test lo puso
    delete window.matchMedia;
});

describe('formatRecordValue', () => {
    it('null y undefined son raya, sin inventar un 0 ni un vacio', () => {
        expect(formatRecordValue(null)).toBe('—');
        expect(formatRecordValue(undefined)).toBe('—');
    });
    it('booleanos: Sí/No por defecto y con traductor', () => {
        expect(formatRecordValue(true)).toBe('Sí');
        expect(formatRecordValue(false)).toBe('No');
        const t = vi.fn((key: string) => `T:${key}`);
        expect(formatRecordValue(true, t as never)).toBe('T:data.yes');
        expect(formatRecordValue(false, t as never)).toBe('T:data.no');
    });
    it('numeros y cadenas pasan tal cual', () => {
        expect(formatRecordValue(0)).toBe('0');
        expect(formatRecordValue('abc')).toBe('abc');
    });
    it('un objeto se resume como clave: valor sin snake_case', () => {
        expect(formatRecordValue({ target_pct: 5, ok: true, nada: null })).toBe('target pct: 5 · ok: Sí · nada: —');
    });
    it('arrays: vacio es raya y mas de 6 elementos cuenta el resto', () => {
        expect(formatRecordValue([])).toBe('—');
        expect(formatRecordValue([1, 2, 3, 4, 5, 6, 7, 8])).toBe('1 · 2 · 3 · 4 · 5 · 6 · +2 más');
    });
    it('objeto vacio es raya y el resto de claves se cuenta en ingles con traductor', () => {
        expect(formatRecordValue({})).toBe('—');
        const t = vi.fn((key: string, params?: { count?: number }) => (key === 'data.moreItems' ? `+${params?.count} more` : key));
        const many = Object.fromEntries(Array.from({ length: 8 }, (_, i) => [`k${i}`, i]));
        expect(formatRecordValue(many, t as never)).toContain('· +2 more');
        expect(formatRecordValue([1, 2, 3, 4, 5, 6, 7], t as never)).toBe('1 · 2 · 3 · 4 · 5 · 6 · +1 more');
    });
    it('fechas en ISO y anidamiento mas alla de la profundidad marcado, no serializado', () => {
        expect(formatRecordValue({ d: new Date('2026-01-02T03:04:05.000Z') })).toBe('d: 2026-01-02T03:04:05.000Z');
        expect(formatRecordValue({ a: { b: { c: 1 } }, l: [[[1, 2]]] })).toBe('a: b: {…} · l: [1]');
    });
    it('un valor compuesto muy largo se recorta a 400 caracteres con puntos suspensivos', () => {
        const out = formatRecordValue({ texto: 'x'.repeat(1000) });
        expect(out).toHaveLength(400);
        expect(out.endsWith('…')).toBe(true);
    });
});

describe('toRecords', () => {
    it('deja los objetos y envuelve primitivos, null y arrays', () => {
        const obj = { a: 1 };
        const out = toRecords([obj, 5, null, [1, 2], 'x']);
        expect(out[0]).toBe(obj);
        expect(out.slice(1)).toEqual([{ value: 5 }, { value: null }, { value: [1, 2] }, { value: 'x' }]);
    });
});

describe('pickColumns', () => {
    it('respeta las columnas preferidas sin recortarlas', () => {
        expect(pickColumns([{ a: 1 }], ['x', 'y', 'z', 'w', 'v', 'u', 't'])).toEqual(['x', 'y', 'z', 'w', 'v', 'u', 't']);
    });
    it('preferred vacio infiere de los datos, saltando objetos anidados y duplicados', () => {
        expect(pickColumns([{ a: 1, o: { x: 1 }, n: null }, { a: 2, b: 3 }], [])).toEqual(['a', 'n', 'b']);
    });
    it('max acota las inferidas y un max invalido se queda en 1', () => {
        const rec = [{ a: 1, b: 2, c: 3 }];
        expect(pickColumns(rec, undefined, 2)).toEqual(['a', 'b', 'c']);
        expect(pickColumns([{ a: 1 }, { b: 2 }, { c: 3 }, { d: 4 }], undefined, 2)).toEqual(['a', 'b']);
        expect(pickColumns([{ a: 1 }, { b: 2 }], undefined, 0)).toEqual(['a']);
    });
    it('sin registros no hay columnas', () => {
        expect(pickColumns([])).toEqual([]);
    });
});

describe('researchHrefFor', () => {
    it('ticker en mayusculas y codificado', () => {
        expect(researchHrefFor({ ticker: ' brk.b ' })).toBe('/research/BRK.B');
    });
    it('sin ticker, en blanco o no cadena devuelve null', () => {
        expect(researchHrefFor({})).toBeNull();
        expect(researchHrefFor({ ticker: '   ' })).toBeNull();
        expect(researchHrefFor({ ticker: 5 })).toBeNull();
    });
    it('admite otra clave', () => {
        expect(researchHrefFor({ symbol: 'aapl' }, 'symbol')).toBe('/research/AAPL');
    });
});

describe('RecordList', () => {
    const rows = [{ ticker: 'aapl', pct: 1.5 }];

    it('lista vacia: estado vacio con mensaje por defecto, o el propio y su accion', () => {
        const { rerender } = render(<RecordList fetchRecords={async () => []} records={[]} title="T" />);
        expect(screen.getAllByText(/./).length).toBeGreaterThan(0);
        rerender(
            <RecordList emptyAction={<button type="button">Crear</button>} emptyMessage="Nada por aqui" fetchRecords={async () => []} records={[]} title="T" />,
        );
        expect(screen.getByText('Nada por aqui')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Crear' })).toBeInTheDocument();
    });

    it('filas sin ninguna columna plana se vuelcan como JSON, y el footer se pinta', () => {
        render(<RecordList fetchRecords={async () => []} footer={<p>Pie</p>} records={[{ o: { a: 1 } }]} title="T" />);
        expect(document.querySelector('pre')?.textContent).toContain('"a": 1');
        expect(screen.getByText('Pie')).toBeInTheDocument();
    });

    it('hideTitle deja el titulo como texto accesible y sin descripcion ni icono', () => {
        render(<RecordList description="Desc" fetchRecords={async () => []} hideTitle icon={<i data-testid="ic" />} records={rows} title="Titulo" />);
        expect(screen.queryByText('Desc')).not.toBeInTheDocument();
        expect(screen.queryByTestId('ic')).not.toBeInTheDocument();
        expect(document.querySelector('.sr-only')?.textContent).toBe('Titulo');
    });

    it('titulo visible con descripcion, icono y nivel h2', () => {
        render(<RecordList description="Desc" fetchRecords={async () => []} icon={<i data-testid="ic" />} records={rows} title="Titulo" titleAs="h2" />);
        expect(screen.getByRole('heading', { level: 2, name: 'Titulo' })).toBeInTheDocument();
        expect(screen.getByText('Desc')).toBeInTheDocument();
        expect(screen.getByTestId('ic')).toBeInTheDocument();
    });

    it('linkColumns enlaza la celda; formatColumns y columnLabels se aplican en tabla y en cards', () => {
        render(
            <RecordList
                columnLabels={{ pct: 'Porcentaje' }}
                columns={['ticker', 'pct']}
                fetchRecords={async () => []}
                formatColumns={{ pct: (v) => `${String(v)} %` }}
                linkColumns={{ ticker: (record) => researchHrefFor(record) }}
                records={[...rows, { ticker: '', pct: 2 }]}
                rowActions={(record) => <button type="button">Accion {String(record.pct)}</button>}
                title="T"
            />,
        );
        // Sin matchMedia se montan tabla y cards: cada enlace y cada texto aparece dos veces.
        const links = screen.getAllByRole('link', { name: 'aapl' });
        expect(links).toHaveLength(2);
        expect(links[0]).toHaveAttribute('href', '/research/AAPL');
        expect(screen.getAllByText('1.5 %').length).toBe(2);
        expect(screen.getAllByText('Porcentaje').length).toBe(3); // 1 cabecera + 1 dt por fila (2 filas)
        expect(screen.getAllByRole('button', { name: 'Accion 2' }).length).toBe(2);
        // ticker en blanco: sin enlace, solo texto
        expect(screen.getAllByRole('link')).toHaveLength(2);
    });

    it('refrescar sustituye los datos; mientras carga el boton queda deshabilitado', async () => {
        let resolve!: (v: unknown[]) => void;
        const fetchRecords = vi.fn(() => new Promise<unknown[]>((r) => { resolve = r; }));
        render(<RecordList fetchRecords={fetchRecords} records={rows} title="T" />);
        const button = screen.getByRole('button', { name: /actualizar|refrescar|refresh/i });
        fireEvent.click(button);
        expect(button).toBeDisabled();
        resolve([{ ticker: 'msft' }, 7]);
        await waitFor(() => expect(screen.getAllByText('msft').length).toBeGreaterThan(0));
        expect(screen.getAllByText('7').length).toBeGreaterThan(0);
        expect(button).not.toBeDisabled();
    });

    it('refrescar sobre una lista vacia muestra el estado de carga, no el vacio', async () => {
        let resolve!: (v: unknown[]) => void;
        const fetchRecords = vi.fn(() => new Promise<unknown[]>((r) => { resolve = r; }));
        const { container } = render(<RecordList fetchRecords={fetchRecords} records={[]} title="T" />);
        fireEvent.click(screen.getByRole('button'));
        expect(container.querySelector('svg.animate-spin.mr-2')).not.toBeNull();
        resolve([]);
        await waitFor(() => expect(container.querySelector('svg.animate-spin.mr-2')).toBeNull());
    });

    it('si refrescar falla avisa con el toast, conserva las filas y ofrece reintentar', async () => {
        const boom = new Error('red caida');
        const fetchRecords = vi.fn().mockRejectedValue(boom);
        render(<RecordList columns={['ticker']} fetchRecords={fetchRecords} records={rows} title="T" />);
        fireEvent.click(screen.getByRole('button'));
        await waitFor(() => expect(toast.showErrorToast).toHaveBeenCalledTimes(1));
        expect(toast.showErrorToast.mock.calls[0][0]).toBe(boom);
        expect(screen.getAllByText('aapl').length).toBeGreaterThan(0);
        // el reintento vuelve a llamar a fetchRecords
        const { onRetry } = toast.showErrorToast.mock.calls[0][1] as { onRetry: () => Promise<void> };
        await onRetry();
        expect(fetchRecords).toHaveBeenCalledTimes(2);
    });
});

describe('RecordDetail', () => {
    it('sin registro o con todas las claves ocultas: estado vacio con su accion', () => {
        const { rerender } = render(<RecordDetail emptyAction={<button type="button">Crear</button>} emptyMessage="Vacio" record={null} title="D" />);
        expect(screen.getByText('Vacio')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Crear' })).toBeInTheDocument();
        rerender(<RecordDetail emptyMessage="Vacio" hiddenKeys={['A']} record={{ a: 1 }} title="D" />);
        expect(screen.getByText('Vacio')).toBeInTheDocument();
        rerender(<RecordDetail record={null} title="D" />);
        expect(screen.getAllByText(/./).length).toBeGreaterThan(0);
    });

    it('pinta clave/valor con etiquetas, formateadores, claves ocultas (sin mayusculas) y maxKeys', () => {
        render(
            <RecordDetail
                actions={<button type="button">Regenerar</button>}
                columnLabels={{ plan: 'Plan' }}
                description="Desc"
                formatColumns={{ monto: (v, rec) => `${String(v)} ${String(rec.moneda)}` }}
                hiddenKeys={['TRACE']}
                icon={<i data-testid="ic" />}
                maxKeys={4}
                record={{ plan: 'ok', monto: 5, moneda: 'EUR', trace: 'secreto', extra: 1, cortada: 2 }}
                title="D"
                titleAs="h2"
            />,
        );
        expect(screen.getByRole('heading', { level: 2, name: 'D' })).toBeInTheDocument();
        expect(screen.getByText('Desc')).toBeInTheDocument();
        expect(screen.getByTestId('ic')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Regenerar' })).toBeInTheDocument();
        expect(screen.getByText('Plan')).toBeInTheDocument();
        expect(screen.getByText('5 EUR')).toBeInTheDocument();
        expect(screen.queryByText('secreto')).not.toBeInTheDocument();
        expect(screen.getByText('extra')).toBeInTheDocument();
        expect(screen.queryByText('cortada')).not.toBeInTheDocument(); // maxKeys=4 tras ocultar trace: plan, monto, moneda, extra
    });

    it('sin fetchRecord no hay boton de refrescar', () => {
        render(<RecordDetail record={{ a: 1 }} title="D" />);
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });

    it('refrescar: un objeto reemplaza, null vacia (estado honesto) y un array se ignora', async () => {
        const fetchRecord = vi.fn()
            .mockResolvedValueOnce({ a: 'nuevo' })
            .mockResolvedValueOnce([1, 2])
            .mockResolvedValueOnce(null);
        render(<RecordDetail emptyMessage="Vacio" fetchRecord={fetchRecord} record={{ a: 'viejo' }} title="D" />);
        const button = screen.getByRole('button');
        fireEvent.click(button);
        await waitFor(() => expect(screen.getByText('nuevo')).toBeInTheDocument());
        fireEvent.click(button);
        await waitFor(() => expect(fetchRecord).toHaveBeenCalledTimes(2));
        expect(screen.getByText('nuevo')).toBeInTheDocument(); // el array no pisa el dato
        fireEvent.click(button);
        await waitFor(() => expect(screen.getByText('Vacio')).toBeInTheDocument());
    });

    it('si refrescar falla avisa con el toast y conserva el dato', async () => {
        const boom = new Error('fallo');
        const fetchRecord = vi.fn().mockRejectedValue(boom);
        render(<RecordDetail fetchRecord={fetchRecord} record={{ a: 'dato' }} title="D" />);
        fireEvent.click(screen.getByRole('button'));
        await waitFor(() => expect(toast.showErrorToast).toHaveBeenCalledTimes(1));
        expect(toast.showErrorToast.mock.calls[0][0]).toBe(boom);
        expect(screen.getByText('dato')).toBeInTheDocument();
        const { onRetry } = toast.showErrorToast.mock.calls[0][1] as { onRetry: () => Promise<void> };
        await onRetry();
        expect(fetchRecord).toHaveBeenCalledTimes(2);
    });

    it('un record nuevo desde el servidor (router.refresh) sustituye al copiado', () => {
        const { rerender } = render(<RecordDetail record={{ a: 'v1' }} title="D" />);
        expect(screen.getByText('v1')).toBeInTheDocument();
        rerender(<RecordDetail record={{ a: 'v2' }} title="D" />);
        expect(screen.getByText('v2')).toBeInTheDocument();
        expect(screen.queryByText('v1')).not.toBeInTheDocument();
    });
});
