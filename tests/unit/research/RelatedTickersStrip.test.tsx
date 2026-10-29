import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RelatedTickersStrip } from '@/components/research/RelatedTickersStrip';
import type { RelatedTicker } from '@/lib/news-related-tickers';
const item = (over: Partial<RelatedTicker> = {}): RelatedTicker => ({ ticker: 'TEST', name: 'Synthetic', currency: 'USD',
    price: 100, date: '2026-01-31', change_pct: 2.5, ...over });

describe('Related ticker strip presentation', () => {
    it.each([undefined, null, []])('renders nothing for absent or empty items %s', items => {
        const view = render(<RelatedTickersStrip items={items} />); expect(view.container).toBeEmptyDOMElement();
    });
    it('shows dated closing prices with signed point changes and correct links, not live quote claims', () => {
        render(<RelatedTickersStrip items={[item({ ticker: 'A/B' }), item({ ticker: 'DOWN', change_pct: -1.5 }), item({ ticker: 'FLAT', change_pct: 0 })]} />);
        const list = screen.getByRole('list', { name: 'Tickers relacionados' });
        expect(within(list).getAllByRole('listitem')).toHaveLength(3);
        expect(screen.getByRole('link', { name: 'A/B' })).toHaveAttribute('href', '/research/A%2FB');
        const first = screen.getByRole('link', { name: 'A/B' }).closest('li')!;
        expect(first).toHaveAttribute('title', 'Synthetic · cierre 2026-01-31');
        expect(within(first).getByText('100,00 US$')).toBeVisible();
        expect(within(first).getByText('+2,50 %')).toHaveClass('text-emerald-300');
        expect(screen.getByText('-1,50 %')).toHaveClass('text-red-300');
        expect(screen.getByText('0,00 %')).toHaveClass('text-gray-300');
        expect(screen.queryByText(/cierre 31\/01/)).not.toBeInTheDocument();
    });
    it('does not invent zero changes or currencies when prices lack comparable closes', () => {
        render(<RelatedTickersStrip items={[item({ ticker: 'GBX', currency: 'GBX', change_pct: null }),
            item({ ticker: 'MISSING', price: null, date: null, change_pct: null }),
            item({ ticker: 'INVALID', currency: null, price: Infinity, change_pct: NaN })]} />);
        const dated = screen.getByRole('link', { name: 'GBX' }).closest('li')!;
        expect(dated).toHaveTextContent('cierre 31/01');
        expect(within(dated).getByText('N/D')).toHaveClass('text-gray-500');
        const missing = screen.getByRole('link', { name: 'MISSING' }).closest('li')!;
        expect(missing).toHaveAttribute('title', 'Synthetic · sin cierre disponible');
        expect(within(missing).getAllByText('N/D')).toHaveLength(2);
        expect(screen.queryByText('0,00 %')).not.toBeInTheDocument();
    });
    it('labels ETF holdings weights without making ETFs company links or inventing a day return', () => {
        render(<RelatedTickersStrip items={[item({ ticker: 'ETF', kind: 'etf', name: 'Fund', weight_pct: 12.5, holdings_as_of: '2026-01-30' }),
            item({ ticker: 'UNKNOWN', kind: 'etf', weight_pct: null })]} />);
        expect(screen.queryByRole('link')).not.toBeInTheDocument();
        expect(screen.getByText('12,5 % del ETF')).toBeVisible();
        expect(screen.getByText('ETF').closest('li')).toHaveAttribute('title', 'ETF Fund · peso del ticker segun holdings oficiales al 2026-01-30');
        expect(screen.getByText('UNKNOWN').closest('li')).toHaveTextContent('N/D');
        expect(screen.queryByText('+2,50 %')).not.toBeInTheDocument();
    });
});
