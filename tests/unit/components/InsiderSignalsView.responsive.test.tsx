import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }) }));
vi.mock('@/lib/actions/insider.actions', () => ({ loadMoreInsiderFilings: vi.fn() }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => null }));

import InsiderSignalsView from '@/components/insider/InsiderSignalsView';
import type { InsiderFilingsResult, InsiderSignalsResult } from '@/lib/actions/insider.actions';

// La vista pintaba DOS árboles por señal: tarjetas móvil (md:hidden, role
// article) y tabla escritorio (hidden md:block). Contrato (decisión de diseño,
// 2026-11-14): UNA tabla responsiva (patrón PositionsTable /watchlist):
// una señal = una fila, con etiquetas móviles md:hidden por celda.
const result = (): InsiderSignalsResult =>
    ({
        ticker: 'ASTS', status: 'ok', filings_scanned: 10, filings_parsed: 10, filings_failed: 0, buy_count: 2,
        signals: [
            { signal: 'cluster_buy', insiders: ['A', 'B'], ticker: 'ASTS', window_start: '2026-09-01', total_value: 500000, detail: 'Dos insiders', form: '4/A', multi_reporter: true, source_url: 'https://sec.gov/f1' },
            { signal: 'big_buy', insider: 'Jane', role: 'Officer', officer_title: 'CEO', date: '2026-10-01', value: 2_000_000, detail: 'Compra grande', form: '4', source_url: 'http://insecure' },
        ],
        provenance: { fetched_at: '2026-10-02T10:00:00Z' },
    }) as unknown as InsiderSignalsResult;

const filings = (): InsiderFilingsResult => ({ ticker: 'ASTS', status: 'ok', count: 0, total: 0, filings: [] }) as InsiderFilingsResult;

describe('InsiderSignalsView responsiva (una fila por señal)', () => {
    it('una señal = una fila (sin árbol duplicado móvil/escritorio)', () => {
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={result()} initialFilings={filings()} />);
        expect(screen.queryAllByRole('article')).toHaveLength(0);
        const table = screen.getByRole('table');
        // Cabecera + 2 señales = 3 filas (antes: 3 en la tabla + 2 artículos).
        expect(within(table).getAllByRole('row')).toHaveLength(3);
        // Cada detalle aparece UNA vez (antes: tarjeta + tabla).
        expect(screen.getAllByText('Compra grande')).toHaveLength(1);
    });

    it('la fila única conserva etiquetas móviles, badge, importe y enlace SEC', () => {
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={result()} initialFilings={filings()} />);
        const rows = within(screen.getByRole('table')).getAllByRole('row');
        expect(within(rows[1]).getByText('Señal')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Insider')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Fecha')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Valor')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Detalle')).toBeInTheDocument();
        expect(within(rows[1]).getByText('500.000 US$')).toBeInTheDocument();
        expect(within(rows[1]).getByRole('link', { name: /Ver filing SEC/ })).toHaveAttribute('href', 'https://sec.gov/f1');
        // http:// no se enlaza.
        expect(within(rows[2]).queryByRole('link')).not.toBeInTheDocument();
    });
});
