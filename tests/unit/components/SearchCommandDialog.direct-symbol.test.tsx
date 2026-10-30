import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const push = vi.fn();
const searchStocksWithStatus = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, prefetch: vi.fn() }) }));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: (q: string) => searchStocksWithStatus(q),
    getPopularStocks: vi.fn().mockResolvedValue([]),
}));
import SearchCommandDialog from '@/components/SearchCommandDialog';

const stock = (symbol: string, name: string) => ({ symbol, name, exchange: 'NYSE', type: 'Common Stock', isInWatchlist: false });

function open() {
    render(<SearchCommandDialog open initialStocks={[stock('AAPL', 'Apple Inc')]} getFocusTarget={() => null} />);
    return screen.getByLabelText('Buscar acciones o secciones');
}

describe('buscador global: ir a la ficha por símbolo', () => {
    beforeEach(() => {
        push.mockReset();
        searchStocksWithStatus.mockReset();
    });

    it('sin sugerencias, ofrece abrir la ficha de lo escrito y navega a ella', async () => {
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [] });
        fireEvent.change(open(), { target: { value: 'ko' } });
        const item = await screen.findByRole('option', { name: /Abrir la ficha de «KO»/ });
        fireEvent.click(item);
        expect(push).toHaveBeenCalledWith('/research/KO');
    });

    it('si la búsqueda falla también deja ir a la ficha', async () => {
        searchStocksWithStatus.mockRejectedValue(new Error('proveedor caído'));
        fireEvent.change(open(), { target: { value: 'sap.de' } });
        expect(await screen.findByRole('option', { name: /Abrir la ficha de «SAP\.DE»/ })).toBeInTheDocument();
    });

    it('no lo ofrece si el símbolo exacto ya está en los resultados, ni para texto que no es un ticker', async () => {
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [stock('KO', 'Coca-Cola Co')] });
        const input = open();
        fireEvent.change(input, { target: { value: 'ko' } });
        await screen.findByRole('option', { name: /Coca-Cola/ });
        expect(screen.queryByRole('option', { name: /Abrir la ficha/ })).toBeNull();
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [] });
        fireEvent.change(input, { target: { value: 'coca cola' } });
        await waitFor(() => expect(searchStocksWithStatus).toHaveBeenCalledWith('coca cola'));
        expect(screen.queryByRole('option', { name: /Abrir la ficha/ })).toBeNull();
    });

    it('con la ficha directa como única salida no dice «Sin resultados» encima', async () => {
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [] });
        fireEvent.change(open(), { target: { value: 'ko' } });
        await waitFor(() => expect(searchStocksWithStatus).toHaveBeenCalledWith('ko'));
        await screen.findByRole('option', { name: /Abrir la ficha de «KO»/ });
        await new Promise((r) => setTimeout(r, 50));
        expect(screen.queryByText('Sin resultados')).toBeNull();
    });

    it('con sugerencias, las empresas van primero y la ficha directa queda debajo', async () => {
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [stock('ITX', 'Itex Corp'), stock('ITXN', 'Otra')] });
        fireEvent.change(open(), { target: { value: 'itx.mc' } });
        await screen.findByRole('option', { name: /Itex Corp/ });
        await screen.findByRole('option', { name: /Abrir la ficha de «ITX\.MC»/ });
        const names = screen.getAllByRole('option').map((o) => o.textContent ?? '');
        const direct = names.findIndex((n) => n.includes('Abrir la ficha'));
        expect(names.findIndex((n) => n.includes('Itex Corp'))).toBeLessThan(direct);
        expect(names.findIndex((n) => n.includes('Otra'))).toBeLessThan(direct);
    });
});
