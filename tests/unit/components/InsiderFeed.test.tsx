import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import InsiderFeed from '@/components/insider/InsiderFeed';
import type { InsiderFeedResult, InsiderFeedTransaction } from '@/lib/actions/insider.actions';

function tx(over: Partial<InsiderFeedTransaction> = {}): InsiderFeedTransaction {
    return {
        ticker: 'ASTS', insider: 'Doe John', role: 'Officer', officer_title: 'CFO', side: 'compra',
        shares: 1000, price: 12.5, currency: 'USD', form: '4', value: 12500, date: '2026-10-01',
        accession_number: 'a-1', ...over,
    };
}

function feed(over: Partial<InsiderFeedResult> = {}): InsiderFeedResult {
    return {
        status: 'ok', days: 90, side: 'all', count: 1,
        totals: { buy_count: 3, buy_value: 2_500_000, sell_count: 1, sell_value: 0, filings_total: 4, filings_with_transactions: 4, filings_pending: 0 },
        clusters: [], c_suite_buys: [], transactions: [tx()], ...over,
    } as InsiderFeedResult;
}

describe('InsiderFeed', () => {
    it.each([null, { ...feed(), status: 'error' }])('sin histórico muestra aviso (%#)', (f) => {
        render(<InsiderFeed feed={f as InsiderFeedResult | null} side="all" days={90} />);
        expect(screen.getByText(/No se pudo leer el histórico insider/)).toBeInTheDocument();
    });

    it('filtros: enlaces con lado y periodo, y página actual marcada', () => {
        render(<InsiderFeed feed={feed()} side="buy" days={365} />);
        const lado = screen.getByRole('navigation', { name: 'Lado' });
        expect(within(lado).getByRole('link', { name: 'Todas' })).toHaveAttribute('href', '/insider?dias=365');
        expect(within(lado).getByRole('link', { name: 'Compras' })).toHaveAttribute('aria-current', 'page');
        expect(within(lado).getByRole('link', { name: 'Ventas' })).toHaveAttribute('href', '/insider?lado=sell&dias=365');
        const periodo = screen.getByRole('navigation', { name: 'Periodo' });
        expect(within(periodo).getByRole('link', { name: '1 año' })).toHaveAttribute('aria-current', 'page');
        expect(within(periodo).getByRole('link', { name: '90 días' })).toHaveAttribute('href', '/insider?lado=buy');
        expect(within(periodo).getByRole('link', { name: '30 días' })).toHaveAttribute('href', '/insider?lado=buy&dias=30');
    });

    it('con valores por defecto el filtro enlaza a /insider limpio', () => {
        render(<InsiderFeed feed={feed()} side="all" days={90} />);
        expect(within(screen.getByRole('navigation', { name: 'Lado' })).getByRole('link', { name: 'Todas' })).toHaveAttribute('href', '/insider');
    });

    it('totales: importes compactos y guion si falta el valor', () => {
        const f = feed();
        (f.totals as { sell_value: unknown }).sell_value = null;
        render(<InsiderFeed feed={f} side="all" days={90} />);
        expect(screen.getByText('Compras', { selector: 'dt' }).nextSibling?.textContent).toMatch(/^3 · /);
        expect(screen.getByText('Ventas', { selector: 'dt' }).nextSibling?.textContent).toBe('1 · —');
        expect(screen.getByText('Clusters', { selector: 'dt' }).nextSibling?.textContent).toBe('0');
        expect(screen.getByText('Compras CEO/CFO', { selector: 'dt' }).nextSibling?.textContent).toBe('0');
    });

    it('señales: clusters, grandes compras y CEO/CFO con etiqueta institucional', () => {
        render(
            <InsiderFeed
                side="all"
                days={90}
                feed={feed({
                    clusters: [{ ticker: 'AAA', insider_count: 4, total_value: 900000, window_start: '2026-09-01' }],
                    big_buys: [{ ticker: 'BRK', insider: 'Berkshire Hathaway Inc', value: 5_000_000, date: '2026-10-02', accession_number: 'b', tx_line: 1 }],
                    c_suite_buys: [{ ticker: 'CCC', insider: 'Jane Roe', role: 'Officer', officer_title: 'CEO', value: 200000, accession_number: 'c', tx_line: 2 }],
                })}
            />,
        );
        expect(screen.getByRole('heading', { name: 'Clusters de compra' })).toBeInTheDocument();
        expect(screen.getByText('4 insiders')).toBeInTheDocument();
        expect(screen.getByText(/desde /)).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Grandes compras' })).toBeInTheDocument();
        expect(screen.getByText('Institucional')).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Compras de CEO y CFO' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'CCC' })).toHaveAttribute('href', '/insider?ticker=CCC');
    });

    it('sin señales no pinta sus secciones', () => {
        render(<InsiderFeed feed={feed()} side="all" days={90} />);
        expect(screen.queryByRole('heading', { name: 'Clusters de compra' })).not.toBeInTheDocument();
        expect(screen.queryByRole('heading', { name: 'Grandes compras' })).not.toBeInTheDocument();
    });

    it('sin operaciones lo dice', () => {
        render(<InsiderFeed feed={feed({ transactions: [] })} side="all" days={90} />);
        expect(screen.getByText('Sin operaciones en este periodo.')).toBeInTheDocument();
    });

    it('operaciones: divisa, enlace a fuente, tramos, 10b5-1 y orígenes no SEC', () => {
        const txs = [
            tx({ source_url: 'https://sec.gov/x', tranches: 3, rule_10b5_1: true }),
            tx({ ticker: 'LLOY', form: 'PDMR', currency: 'GBP', accession_number: 'a-2', side: 'venta' }),
            tx({ ticker: 'SHOP', form: 'CA-INSIDER', currency: null, accession_number: 'a-3' }),
            tx({ ticker: 'NONE', currency: 'XXXX', price: null, value: null, shares: null, date: null, accession_number: 'a-4', insider: null }),
        ];
        render(<InsiderFeed feed={feed({ transactions: txs })} side="all" days={90} />);
        const table = screen.getByRole('table');
        const rows = within(table).getAllByRole('row');
        expect(rows).toHaveLength(5);
        expect(within(rows[1]).getByRole('link', { name: /12,500/ })).toHaveAttribute('href', 'https://sec.gov/x');
        expect(within(rows[1]).getByText('3 tramos · precio medio')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Plan 10b5-1')).toBeInTheDocument();
        expect(within(rows[2]).getByText('PDMR (Reino Unido)')).toBeInTheDocument();
        expect(within(rows[3]).getByText('Canadá · fuente no oficial (Yahoo)')).toBeInTheDocument();
        expect(within(rows[3]).getByText('Divisa no informada')).toBeInTheDocument();
        expect(within(rows[4]).getAllByText('—').length).toBeGreaterThan(0);
        // la tarjeta móvil repite lo mismo
        expect(screen.getAllByText('Divisa no informada').length).toBeGreaterThanOrEqual(2);
        expect(screen.getByText(/Fuente: tracefour/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'SEDI' })).toHaveAttribute('href', 'https://www.sedi.ca');
        expect(screen.getAllByRole('link', { name: /12,500/ })).toHaveLength(2);
    });
});
