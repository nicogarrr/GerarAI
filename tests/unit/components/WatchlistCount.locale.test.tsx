import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import { WatchlistCount, WatchlistMembership, useConfirmWatchlistRemoval } from '@/components/watchlist/WatchlistMembership';
function Remove() { const remove = useConfirmWatchlistRemoval(); return <button onClick={() => remove('AAPL')}>remove</button>; }
describe('Watchlist count follows the selected language', () => {
    it.each([
        ['en', '2 companies · Page 2 of 3', '1 company · Page 2 of 3', '0 companies · Page 2 of 3'],
        ['es', '2 empresas · Página 2 de 3', '1 empresa · Página 2 de 3', '0 empresas · Página 2 de 3'],
    ] as const)('%s keeps page and plural correct when confirmed removal changes membership', (locale, two, one, zero) => {
        const { container, rerender } = render(<LocaleProvider locale={locale}><WatchlistMembership><WatchlistCount symbols={['AAPL', 'MSFT']} page={2} totalPages={3} /><Remove /></WatchlistMembership></LocaleProvider>);
        expect(container.querySelector('[aria-live="polite"]')).toHaveTextContent(two);
        expect(container.querySelector('.whitespace-nowrap')).toHaveTextContent(locale === 'en' ? 'Page 2 of 3' : 'Página 2 de 3');
        fireEvent.click(screen.getByText('remove'));
        expect(container.querySelector('[aria-live="polite"]')).toHaveTextContent(one);
        rerender(<LocaleProvider locale={locale}><WatchlistMembership><WatchlistCount symbols={[]} page={2} totalPages={3} /><Remove /></WatchlistMembership></LocaleProvider>);
        expect(container.querySelector('[aria-live="polite"]')).toHaveTextContent(zero);
    });
});

it('keeps the complete translated page label inside the no-wrap span', () => {
    const { container } = render(<LocaleProvider locale="en"><WatchlistMembership><WatchlistCount symbols={['MSFT']} page={120} totalPages={240} /></WatchlistMembership></LocaleProvider>);
    const label = screen.getByText('Page 120 of 240');
    expect(label).toHaveClass('whitespace-nowrap');
    expect(container.querySelectorAll('.whitespace-nowrap')).toHaveLength(1);
});
