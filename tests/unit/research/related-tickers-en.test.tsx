import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RelatedTickersStrip } from '@/components/research/RelatedTickersStrip';
import { relatedTickerView, type RelatedTicker } from '@/lib/news-related-tickers';

const item = (over: Partial<RelatedTicker> = {}): RelatedTicker => ({ ticker: 'TEST', name: 'Synthetic', currency: 'USD',
    price: 1234.5, date: '2026-01-31', change_pct: 2.5, ...over });

// Con English, la tira de tickers de una noticia seguía en castellano y con
// números en formato español («1234,50 US$», «cierre 31/01», «N/D»).
describe('tickers relacionados de una noticia en inglés', () => {
    it('precio, variación, fecha y título en inglés', () => {
        render(<RelatedTickersStrip locale="en" items={[item(), item({ ticker: 'OLD', change_pct: null }), item({ ticker: 'NOP', price: null, change_pct: null, date: null })]} />);
        const list = screen.getByRole('list', { name: 'Related tickers' });
        const first = within(list).getByRole('link', { name: 'TEST' }).closest('li')!;
        expect(first).toHaveAttribute('title', 'Synthetic · close 2026-01-31');
        expect(within(first).getByText('$1,234.50')).toBeVisible();
        expect(within(first).getByText('+2.50%')).toBeVisible();
        const old = within(list).getByRole('link', { name: 'OLD' }).closest('li')!;
        expect(within(old).getByText('close 01/31')).toBeVisible();
        expect(within(old).getByText('N/A')).toBeVisible();
        const none = within(list).getByRole('link', { name: 'NOP' }).closest('li')!;
        expect(none).toHaveAttribute('title', 'Synthetic · no close available');
        expect(list.textContent).not.toMatch(/cierre|N\/D|US\$/);
    });

    it('ETF temático en inglés', () => {
        const view = relatedTickerView({ ticker: 'SMH', name: 'VanEck Semiconductor', kind: 'etf', weight_pct: 21.25, holdings_as_of: '2026-01-30', price: null, date: null, change_pct: null }, 'en');
        expect(view.priceText).toBe('21.25% of the ETF');
        expect(view.title).toBe('ETF VanEck Semiconductor · ticker weight per official holdings as of 2026-01-30');
    });

    it('en castellano sigue igual', () => {
        render(<RelatedTickersStrip items={[item({ change_pct: null })]} />);
        const list = screen.getByRole('list', { name: 'Tickers relacionados' });
        expect(within(list).getByText('1.234,50 US$')).toBeVisible();
        expect(within(list).getByText('cierre 31/01')).toBeVisible();
    });
});
