import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const push = vi.fn();
const loadMore = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh: vi.fn(), replace: vi.fn() }) }));
vi.mock('@/lib/actions/insider.actions', () => ({
    loadMoreInsiderFilings: (...args: unknown[]) => loadMore(...args),
}));
// Borde de búsqueda (llama a una server action): se sustituye por un input simple.
vi.mock('@/components/search/TickerSearchInput', () => ({
    TickerSearchInput: (props: {
        value: string;
        onValueChange: (v: string) => void;
        onSelect: (s: { symbol: string }) => void;
        ariaLabel: string;
    }) => (
        <div>
            <input aria-label={props.ariaLabel} value={props.value} onChange={(e) => props.onValueChange(e.target.value)} />
            <button type="button" onClick={() => props.onSelect({ symbol: 'meta' })}>elegir META</button>
        </div>
    ),
}));

import InsiderSignalsView from '@/components/insider/InsiderSignalsView';
import type { InsiderFilingEntry, InsiderFilingsResult, InsiderSignalsResult } from '@/lib/actions/insider.actions';

const signals = (over: Partial<InsiderSignalsResult> = {}): InsiderSignalsResult =>
    ({
        ticker: 'ASTS', status: 'ok', filings_scanned: 10, filings_parsed: 10, filings_failed: 0, buy_count: 2,
        signals: [
            {
                signal: 'cluster_buy', insiders: ['A', 'B'], ticker: 'ASTS', window_start: '2026-09-01', total_value: 500000,
                detail: 'Dos insiders', form: '4/A', multi_reporter: true, source_url: 'https://sec.gov/f1',
            },
            { signal: 'big_buy', insider: 'Jane', role: 'Officer', officer_title: 'CEO', date: '2026-10-01', value: 2_000_000, detail: 'Compra grande', form: '4', source_url: 'http://insecure' },
            { signal: 'other', insider: 'Bob', value: 'raro', date: 5 },
        ],
        provenance: { fetched_at: '2026-10-02T10:00:00Z' },
        ...over,
    }) as unknown as InsiderSignalsResult;

const filing = (n: number, over: Partial<InsiderFilingEntry> = {}): InsiderFilingEntry => ({
    accession_number: `acc-${n}`, form: '4', is_amendment: false, filing_date: '2026-10-01', source_url: 'https://sec.gov/x',
    transaction_count: 1,
    transactions: [{ insider: 'Doe', role: 'Officer', officer_title: 'CFO', code: 'P', shares: 100, price: 10, value: 1000, is_derivative: false, security_title: null, rule_10b5_1: false }],
    ...over,
} as InsiderFilingEntry);

const filings = (list: InsiderFilingEntry[], over: Partial<InsiderFilingsResult> = {}): InsiderFilingsResult =>
    ({ ticker: 'ASTS', status: 'ok', count: list.length, total: list.length, filings: list, ...over }) as InsiderFilingsResult;

beforeEach(() => {
    push.mockReset();
    loadMore.mockReset();
});

describe('InsiderSignalsView', () => {
    it('respuesta vacía antes de completar la página conserva la actual y permite reintentar', async () => {
        loadMore.mockResolvedValueOnce(filings([filing(21), filing(22)], {total: 25}))
            .mockResolvedValueOnce(filings([], {total: 25}))
            .mockResolvedValueOnce(filings([filing(23), filing(24), filing(25)], {total: 25}));
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings(Array.from({length: 20}, (_, i) => filing(i + 1)), {total: 25})} />);
        fireEvent.click(screen.getByRole('button', {name: /Página siguiente/}));
        await waitFor(() => expect(loadMore).toHaveBeenCalledTimes(2));
        expect(screen.getByText('Página 1 de 2')).toBeInTheDocument();
        expect(screen.getByRole('alert')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', {name: /Página siguiente/}));
        await waitFor(() => expect(screen.getByText('Página 2 de 2')).toBeInTheDocument());
        expect(loadMore).toHaveBeenLastCalledWith('ASTS', 22);
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('buscar navega con el ticker en mayúsculas y vacío no navega', () => {
        render(<InsiderSignalsView initialTicker="" initialResult={null} />);
        const input = screen.getByRole('textbox');
        fireEvent.submit(input.closest('form')!);
        expect(push).not.toHaveBeenCalled();
        fireEvent.change(input, { target: { value: ' meta ' } });
        fireEvent.click(screen.getByRole('button', { name: 'Buscar' }));
        expect(push).toHaveBeenCalledWith('/insider?ticker=META');
        fireEvent.click(screen.getByRole('button', { name: 'elegir META' }));
        expect(push).toHaveBeenLastCalledWith('/insider?ticker=META');
        expect(screen.queryByText(/Lectura parcial/)).not.toBeInTheDocument();
    });

    it('lectura parcial y fallo total de señales', () => {
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={null} initialFilings={null} />);
        expect(screen.getByText(/Lectura parcial: una de las fuentes no respondió/)).toBeInTheDocument();
        expect(screen.getByText(/No se pudieron cargar las señales de ASTS/)).toBeInTheDocument();
    });

    it('emisor no SEC: mensaje y detalle técnico solo si la razón no es la estable', () => {
        const { rerender } = render(
            <InsiderSignalsView initialTicker="SAN" initialResult={{ ticker: 'SAN', status: 'unavailable', reason: 'not a US SEC filer', signals: [] }} initialFilings={filings([])} />,
        );
        expect(screen.getByText(/no es un emisor SEC estadounidense/)).toBeInTheDocument();
        expect(screen.queryByText(/Detalle técnico/)).not.toBeInTheDocument();
        rerender(<InsiderSignalsView initialTicker="SAN" initialResult={{ ticker: 'SAN', status: 'unavailable', reason: 'EDGAR caído', signals: [] }} initialFilings={filings([])} />);
        expect(screen.getByText(/Detalle técnico: EDGAR caído/)).toBeInTheDocument();
    });

    it('degradado: no es ausencia de actividad; con filings guardados lo dice', () => {
        const result = { ticker: 'ASTS', status: 'degraded', filings_scanned: 5, filings_failed: 5, signals: [] } as unknown as InsiderSignalsResult;
        const { rerender } = render(<InsiderSignalsView initialTicker="ASTS" initialResult={result} initialFilings={filings([])} />);
        expect(screen.getByText(/no una ausencia de actividad insider/)).toBeInTheDocument();
        expect(screen.getByText(/Reintenta más tarde\./)).toBeInTheDocument();
        rerender(<InsiderSignalsView initialTicker="ASTS" initialResult={result} initialFilings={filings([filing(1), filing(2)])} />);
        expect(screen.getByText(/Debajo se muestran los 2 filings guardados/)).toBeInTheDocument();
    });

    it('lectura durable degradada muestra cabecera', () => {
        render(
            <InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings([], { status: 'unavailable', reason: 'OperationalError' })} />,
        );
        expect(screen.getAllByText(/Detalle técnico/).length).toBeGreaterThan(0);
    });

    it('parcial: avisa de cobertura incompleta con los números y los warnings', () => {
        render(
            <InsiderSignalsView
                initialTicker="ASTS"
                initialResult={signals({ status: 'partial', filings_parsed: 7, filings_scanned: 10, filings_failed: 3, warnings: ['Aviso uno.', 'Aviso dos.'] })}
                initialFilings={filings([])}
            />,
        );
        expect(screen.getByText(/lectura incompleta/)).toHaveTextContent(/7 de\s*10 Form 4 leídos/);
        expect(screen.getByText(/Aviso uno\. Aviso dos\./)).toBeInTheDocument();
    });

    it('sin señales explica cuántos filings se analizaron', () => {
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals({ signals: [] })} initialFilings={filings([])} />);
        expect(screen.getByText(/ASTS:/)).toBeInTheDocument();
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('señales: etiquetas, importes USD, formulario, enlace SEC solo https', () => {
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings([])} />);
        const table = screen.getByRole('table');
        const rows = within(table).getAllByRole('row');
        expect(rows).toHaveLength(4);
        expect(within(rows[1]).getByText('Enmienda 4/A')).toBeInTheDocument();
        expect(within(rows[1]).getByText('filing conjunto')).toBeInTheDocument();
        expect(within(rows[1]).getByRole('link', { name: /Ver filing SEC/ })).toHaveAttribute('href', 'https://sec.gov/f1');
        expect(within(rows[1]).getByText('$500,000')).toBeInTheDocument();
        expect(within(rows[2]).getByText('Form 4')).toBeInTheDocument();
        expect(within(rows[2]).getByText('$2,000,000')).toBeInTheDocument();
        // http:// no se enlaza
        expect(within(rows[2]).queryByRole('link')).not.toBeInTheDocument();
        expect(within(rows[3]).getByText('raro')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'ASTS' })).toHaveAttribute('href', '/research/ASTS');
        expect(screen.getByText(/3 señales/)).toBeInTheDocument();
    });

    it('señales sin fecha de lectura no inventan fecha', () => {
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals({ provenance: undefined })} initialFilings={filings([])} />);
        expect(screen.getByText(/datos al/)).toBeInTheDocument();
    });

    it('filings: transacciones, derivados, 10b5-1, vacíos y enmienda', () => {
        const list = [
            filing(1, { is_amendment: true, source_url: null }),
            filing(2, {
                transactions: [
                    { insider: null, role: null, officer_title: null, code: 'M', shares: null, price: null, value: 0, is_derivative: true, security_title: 'Opción', rule_10b5_1: true },
                    { insider: 'X', role: null, officer_title: null, code: 'S', shares: 5, price: 3, value: 15, is_derivative: false, security_title: null, rule_10b5_1: false },
                ] as InsiderFilingEntry['transactions'],
            }),
            filing(3, { transactions: [], filing_date: null }),
        ];
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings(list)} />);
        expect(screen.getByText('Filings persistidos · 3')).toBeInTheDocument();
        expect(screen.getByText('Enmienda')).toBeInTheDocument();
        expect(screen.getByText(/derivado/)).toBeInTheDocument();
        expect(screen.getByText(/plan 10b5-1/)).toBeInTheDocument();
        expect(screen.getByText(/Opción/)).toBeInTheDocument();
        expect(screen.getByText('Sin operaciones extraídas.')).toBeInTheDocument();
        expect(screen.getByText('Mostrando 1-3 de 3')).toBeInTheDocument();
        expect(screen.queryByRole('navigation', { name: /Paginación/ })).not.toBeInTheDocument();
    });

    const many = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, k) => filing(from + k));

    it('paginación: «Siguiente» pide por offset los filings que faltan y muestra esa página, sin duplicar', async () => {
        loadMore.mockResolvedValueOnce({ status: 'ok', filings: [...many(20, 25)] });
        render(
            <InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings(many(1, 20), { total: 25 })} />,
        );
        expect(screen.getByText('Mostrando 1-20 de 25')).toBeInTheDocument();
        expect(screen.getByText('Página 1 de 2')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Cargar más' })).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /Página siguiente/ }));
        await waitFor(() => expect(screen.getByText('Mostrando 21-25 de 25')).toBeInTheDocument());
        expect(loadMore).toHaveBeenCalledWith('ASTS', 20);
        expect(screen.getByText('Página 2 de 2')).toBeInTheDocument();
        // Volver atrás no vuelve a pedir nada.
        fireEvent.click(screen.getByRole('button', { name: /Página anterior/ }));
        expect(screen.getByText('Mostrando 1-20 de 25')).toBeInTheDocument();
        expect(loadMore).toHaveBeenCalledTimes(1);
    });

    it('paginación: si falla la carga se avisa, se queda en la página actual y se puede reintentar', async () => {
        loadMore.mockResolvedValueOnce({ status: 'unavailable', reason: 'x', filings: [] });
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings(many(1, 20), { total: 40 })} />);
        fireEvent.click(screen.getByRole('button', { name: /Página siguiente/ }));
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar más filings.');
        expect(screen.getByText('Mostrando 1-20 de 40')).toBeInTheDocument();
        loadMore.mockResolvedValueOnce({ status: 'ok', filings: many(21, 40) });
        fireEvent.click(screen.getByRole('button', { name: /Página siguiente/ }));
        await waitFor(() => expect(screen.getByText('Mostrando 21-40 de 40')).toBeInTheDocument());
        expect(loadMore).toHaveBeenCalledTimes(2);
    });

    it('paginación: mientras carga no hay llamadas dobles', async () => {
        let resolve!: (v: unknown) => void;
        loadMore.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings(many(1, 20), { total: 40 })} />);
        fireEvent.click(screen.getByRole('button', { name: /Página siguiente/ }));
        await waitFor(() => expect(screen.getByRole('button', { name: /Página siguiente/ })).toBeDisabled());
        resolve({ status: 'ok', filings: many(21, 40) });
        await waitFor(() => expect(screen.getByText('Mostrando 21-40 de 40')).toBeInTheDocument());
        expect(loadMore).toHaveBeenCalledTimes(1);
    });
});
