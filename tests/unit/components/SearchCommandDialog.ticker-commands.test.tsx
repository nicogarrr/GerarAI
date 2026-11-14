import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const push = vi.fn();
const searchStocksWithStatus = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, prefetch: vi.fn() }) }));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: (q: string) => searchStocksWithStatus(q),
    getPopularStocks: vi.fn().mockResolvedValue([]),
}));
import { LocaleProvider } from '@/lib/i18n/client';
import SearchCommandDialog from '@/components/SearchCommandDialog';

/**
 * Las etiquetas de los comandos de ficha («ASTS FA») salen del diccionario:
 * en castellano se ve el texto de siempre y con English activado se traduce.
 * Antes el literal español estaba hardcodeado en lib/research/ticker-commands.ts.
 */
function open(locale: 'es' | 'en') {
    render(
        <LocaleProvider locale={locale}>
            <SearchCommandDialog open initialStocks={[]} getFocusTarget={() => null} />
        </LocaleProvider>,
    );
    return screen.getByRole('combobox');
}

describe('buscador global: comandos de ficha traducidos', () => {
    beforeEach(() => {
        push.mockReset();
        searchStocksWithStatus.mockReset();
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [] });
    });

    it('en castellano el comando exacto muestra la etiqueta de siempre y navega', async () => {
        fireEvent.change(open('es'), { target: { value: 'ASTS FA' } });
        const item = await screen.findByRole('option', { name: /ASTS FA/ });
        expect(item).toHaveTextContent('Financieros');
        fireEvent.click(item);
        expect(push).toHaveBeenCalledWith('/research/ASTS?view=financials');
    });

    it('en castellano el prefijo parcial sugiere el comando con su etiqueta, sin fijarlo', async () => {
        fireEvent.change(open('es'), { target: { value: 'ASTS T' } });
        const item = await screen.findByRole('option', { name: /ASTS TESIS/ });
        expect(item).toHaveTextContent('Tesis');
        expect(screen.queryByRole('option', { name: /ASTS FA/ })).toBeNull();
    });

    it('con English activado las etiquetas se traducen', async () => {
        fireEvent.change(open('en'), { target: { value: 'ASTS FA' } });
        const item = await screen.findByRole('option', { name: /ASTS FA/ });
        expect(item).toHaveTextContent('Financials');
        expect(item).not.toHaveTextContent('Financieros');
    });
});
