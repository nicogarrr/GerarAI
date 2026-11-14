import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import InsiderFeed from '@/components/insider/InsiderFeed';
import type { InsiderFeedResult, InsiderFeedTransaction } from '@/lib/actions/insider.actions';

// El feed pintaba DOS árboles por operación: tarjetas móvil (md:hidden,
// role article) y tabla escritorio (hidden md:block). Contrato (decisión de
// diseño, 2026-11-14): UNA tabla responsiva (patrón #5653/#5659/#5663/#5665):
// una operación = una fila, con etiquetas móviles md:hidden por celda.
function tx(over: Partial<InsiderFeedTransaction> = {}): InsiderFeedTransaction {
    return {
        ticker: 'ASTS', insider: 'Doe John', role: 'Officer', officer_title: 'CFO', side: 'compra',
        shares: 1000, price: 12.5, currency: 'USD', form: '4', value: 12500, date: '2026-10-01',
        accession_number: 'a-1', ...over,
    };
}

function feed(over: Partial<InsiderFeedResult> = {}): InsiderFeedResult {
    return {
        status: 'ok', days: 90, side: 'all', count: 2,
        totals: { buy_count: 2, buy_value: 25000, sell_count: 0, sell_value: 0, filings_total: 2, filings_with_transactions: 2, filings_pending: 0 },
        clusters: [], c_suite_buys: [],
        transactions: [
            tx({ source_url: 'https://sec.gov/x', tranches: 3, rule_10b5_1: true }),
            tx({ ticker: 'SHOP', form: 'CA-INSIDER', currency: null, accession_number: 'a-3', source_url: null }),
        ],
        ...over,
    } as InsiderFeedResult;
}

describe('InsiderFeed responsivo (una fila por operación)', () => {
    it('una operación = una fila (sin árbol duplicado móvil/escritorio)', () => {
        render(<InsiderFeed feed={feed()} side="all" days={90} />);
        expect(screen.queryAllByRole('article')).toHaveLength(0);
        const table = screen.getByRole('table');
        // Cabecera + 2 operaciones = 3 filas (antes: 3 en la tabla + 2 artículos).
        expect(within(table).getAllByRole('row')).toHaveLength(3);
        // Cada importe enlazado aparece UNA vez (antes: tarjeta + tabla).
        expect(screen.getAllByRole('link', { name: /12\.500/ })).toHaveLength(1);
        // La nota de divisa ausente aparece UNA vez por operación afectada.
        expect(screen.getAllByText('Divisa no informada')).toHaveLength(1);
    });

    it('la fila única conserva etiquetas móviles, badges y enlaces de fuente', () => {
        render(<InsiderFeed feed={feed()} side="all" days={90} />);
        const rows = within(screen.getByRole('table')).getAllByRole('row');
        // Móvil compacto (rejilla 2 col como la tarjeta antigua, medida a
        // 390px): etiqueta solo en los campos numéricos; identidad y fecha se
        // leen solas en la cabecera de la fila.
        for (const label of ['Acciones', 'Precio', 'Importe']) {
            expect(within(rows[1]).getByText(label)).toBeInTheDocument();
        }
        expect(rows[1].className).toContain('grid grid-cols-2');
        expect(within(rows[1]).getByText(/oct 2026/)).toBeInTheDocument();
        expect(within(rows[1]).getByText('Doe John')).toBeInTheDocument();
        expect(within(rows[1]).getByText('CFO')).toBeInTheDocument();
        expect(within(rows[1]).getByText('3 tramos · precio medio')).toBeInTheDocument();
        expect(within(rows[1]).getByText('Plan 10b5-1')).toBeInTheDocument();
        expect(within(rows[1]).getByRole('link', { name: /12\.500/ })).toHaveAttribute('href', 'https://sec.gov/x');
        // La fila canadiense conserva su aviso y el enlace SEDI (antes solo en la tarjeta).
        expect(within(rows[2]).getByText('Canadá · fuente no oficial')).toBeInTheDocument();
        expect(within(rows[2]).getByRole('link', { name: 'SEDI' })).toHaveAttribute('href', 'https://www.sedi.ca');
        // http ausente: sin enlace de importe en la segunda fila.
        expect(within(rows[2]).queryByRole('link', { name: /12\.500/ })).not.toBeInTheDocument();
    });

    it('el orden DOM de la fila coincide con el orden visual en 390 (WCAG 1.3.2)', () => {
        render(<InsiderFeed feed={feed()} side="all" days={90} />);
        const rows = within(screen.getByRole('table')).getAllByRole('row');
        const cells = within(rows[1]).getAllByRole('cell');
        const texts = cells.map((c) => c.textContent ?? '');
        // Orden visual medido en capturas 390 (2026-11-14): Ticker, Fecha,
        // Operacion, Insider, Rol, Acciones, Precio, Importe. El lector de
        // pantalla recorre el DOM: debe anunciar la misma secuencia.
        expect(texts[0]).toContain('ASTS');
        expect(texts[1]).toMatch(/oct 2026/);
        expect(texts[2]).toContain('Compra');
        expect(texts[3]).toContain('Doe John');
        expect(texts[4]).toContain('CFO');
        expect(texts[5]).toContain('1.000');
        expect(texts[6]).toContain('12,5');
        expect(texts[7]).toContain('12.500');
        // Sin clases order-N: la secuencia visual no puede divergir del DOM.
        for (const cell of cells) expect(cell.className).not.toMatch(/\border-\d/);
    });
});
