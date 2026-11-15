import { render, screen } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RecordList, type DataRecord } from '@/components/data/RecordViews';

// Scorecard v1, hallazgo 4: la lista pintaba DOS arboles (tabla escritorio +
// cards movil) siempre montados; solo uno es visible por CSS. Tras montar debe
// quedar un solo arbol segun el viewport; el SSR sigue saliendo con los dos
// (sin flash ni cambio de payload).

const records = (n: number): DataRecord[] =>
    Array.from({ length: n }, (_, i) => ({ id: i + 1, ticker: `T${i + 1}` }));

function mockMatchMedia(desktop: boolean) {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches: query === 'print' ? false : desktop,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
}

afterEach(() => {
    // @ts-expect-error limpiar el mock
    delete window.matchMedia;
});

describe('RecordList: un solo arbol por viewport tras montar', () => {
    it('SSR y primera pintada montan los dos arboles (sin flash)', () => {
        const html = renderToString(<RecordList fetchRecords={async () => []} records={records(3)} title="Prueba" />);
        expect(html).toContain('<table');
        expect(html).toContain('md:hidden');
    });
    it('viewport escritorio: solo queda la tabla', () => {
        mockMatchMedia(true);
        const { container } = render(<RecordList fetchRecords={async () => []} records={records(3)} title="Prueba" />);
        expect(container.querySelector('table')).not.toBeNull();
        expect(container.querySelector('ul.md\\:hidden')).toBeNull();
    });
    it('viewport movil: solo quedan las cards', () => {
        mockMatchMedia(false);
        const { container } = render(<RecordList fetchRecords={async () => []} records={records(3)} title="Prueba" />);
        expect(container.querySelector('table')).toBeNull();
        expect(container.querySelector('ul.md\\:hidden')).not.toBeNull();
    });
    it('sin matchMedia (jsdom/antiguos) se mantienen los dos arboles', () => {
        const { container } = render(<RecordList fetchRecords={async () => []} records={records(3)} title="Prueba" />);
        expect(container.querySelector('table')).not.toBeNull();
        expect(container.querySelector('ul.md\\:hidden')).not.toBeNull();
    });
    it('los datos visibles no cambian: misma fila en el arbol que queda', () => {
        mockMatchMedia(true);
        render(<RecordList fetchRecords={async () => []} records={records(3)} title="Prueba" />);
        expect(screen.getByText('T3')).toBeInTheDocument();
    });
});
