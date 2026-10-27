import { describe, expect, it } from 'vitest';

import { sortWatchlistRows } from '@/lib/watchlist/sort-rows';

type Row = { symbol: string; price: number | null; pe: number | null };

const metric = (row: Row) => row.pe;
const symbols = (rows: Row[]) => rows.map((r) => r.symbol);

describe('sortWatchlistRows', () => {
    it('por símbolo conserva el orden alfabético aunque falte el precio', () => {
        const rows: Row[] = [
            { symbol: 'AAPL', price: 200, pe: 30 },
            { symbol: 'BABA', price: null, pe: null },
            { symbol: 'CSCO', price: 50, pe: 15 },
        ];
        expect(symbols(sortWatchlistRows(rows, 'symbol', 'asc', metric))).toEqual(['AAPL', 'BABA', 'CSCO']);
        expect(symbols(sortWatchlistRows([...rows].reverse(), 'symbol', 'desc', metric))).toEqual(['CSCO', 'BABA', 'AAPL']);
    });

    it('en «añadido» hunde las filas sin precio y respeta el resto del orden', () => {
        const rows: Row[] = [
            { symbol: 'NEW', price: null, pe: null },
            { symbol: 'MID', price: 10, pe: 5 },
            { symbol: 'OLD', price: 20, pe: 8 },
        ];
        expect(symbols(sortWatchlistRows(rows, 'added', 'desc', metric))).toEqual(['MID', 'OLD', 'NEW']);
    });

    it('por métrica deja los N/D al final en ambas direcciones', () => {
        const rows: Row[] = [
            { symbol: 'A', price: 1, pe: null },
            { symbol: 'B', price: 1, pe: 20 },
            { symbol: 'C', price: 1, pe: 10 },
        ];
        expect(symbols(sortWatchlistRows(rows, 'pe', 'asc', metric))).toEqual(['C', 'B', 'A']);
        expect(symbols(sortWatchlistRows(rows, 'pe', 'desc', metric))).toEqual(['B', 'C', 'A']);
    });

    it('no muta el array de entrada', () => {
        const rows: Row[] = [
            { symbol: 'X', price: null, pe: null },
            { symbol: 'Y', price: 1, pe: 1 },
        ];
        sortWatchlistRows(rows, 'added', 'desc', metric);
        expect(symbols(rows)).toEqual(['X', 'Y']);
    });
});
