import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const h = vi.hoisted(() => ({ add: vi.fn(), refresh: vi.fn(), success: vi.fn(), showError: vi.fn() }));
vi.mock('@/lib/actions/watchlist.actions', () => ({ addToWatchlistCanonical: h.add }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: h.refresh }) }));
vi.mock('sonner', () => ({ toast: { success: h.success } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: h.showError }));
vi.mock('@/components/search/TickerSearchInput', () => ({
    TickerSearchInput: (p: any) => (
        <div>
            <input aria-label="q" value={p.value} disabled={p.disabled} onChange={(e) => p.onValueChange(e.target.value)} />
            <button onClick={() => p.onSelect({ symbol: 'SAN.MC', name: 'Santander', exchange: 'BME', type: 'EQ', isInWatchlist: false })}>pick-san</button>
            <button onClick={() => p.onSelect({ symbol: 'AAPL', name: '', exchange: '', type: '', isInWatchlist: false })}>pick-aapl</button>
            <output data-testid="disabled">{p.disabledSymbols.join(',')}</output>
        </div>
    ),
}));
import WatchlistAddButton from '@/components/watchlist/WatchlistAddButton';

function open(followed: string[] = []) {
    render(<WatchlistAddButton followedSymbols={followed} />);
    fireEvent.click(screen.getByRole('button', { name: /Añadir empresa/ }));
    return within(screen.getByRole('dialog'));
}
const type = (d: ReturnType<typeof open>, v: string) => fireEvent.change(d.getByLabelText('q'), { target: { value: v } });

beforeEach(() => vi.clearAllMocks());

describe('WatchlistAddButton alta', () => {
    it('seleccionar un resultado lo anade con su nombre, avisa y refresca', async () => {
        h.add.mockResolvedValue({ success: true });
        const d = open();
        fireEvent.click(d.getByText('pick-san'));
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('SAN.MC añadido a la watchlist'));
        expect(h.add).toHaveBeenCalledWith('SAN.MC', 'Santander');
        expect(h.refresh).toHaveBeenCalled();
        expect(d.getByTestId('disabled').textContent).toContain('SAN.MC');
    });

    it('sin nombre pasa undefined, no cadena vacia', async () => {
        h.add.mockResolvedValue({ success: true });
        const d = open();
        fireEvent.click(d.getByText('pick-aapl'));
        await waitFor(() => expect(h.add).toHaveBeenCalledWith('AAPL', undefined));
    });

    it('un ticker ya seguido no se vuelve a anadir', () => {
        const d = open(['aapl']);
        fireEvent.click(d.getByText('pick-aapl'));
        expect(h.add).not.toHaveBeenCalled();
        expect(d.getByTestId('disabled').textContent).toBe('AAPL');
    });

    it('duplicado devuelto por el servidor: se marca como seguido y se avisa', async () => {
        h.add.mockResolvedValue({ success: false, code: 'duplicate', message: 'dup' });
        const d = open();
        fireEvent.click(d.getByText('pick-aapl'));
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(h.showError.mock.calls[0][0]).toBe('dup');
        expect(h.showError.mock.calls[0][1]).toMatchObject({ duplicateMessage: 'Ya sigues este ticker.' });
        expect(d.getByTestId('disabled').textContent).toContain('AAPL');
        expect(h.success).not.toHaveBeenCalled();
    });

    it('otro error: no se marca como seguido, texto de reserva y reintento', async () => {
        h.add.mockResolvedValue({ success: false });
        const d = open();
        fireEvent.click(d.getByText('pick-aapl'));
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(h.showError.mock.calls[0][0]).toBe('No se pudo añadir a la watchlist');
        expect(d.getByTestId('disabled').textContent).toBe('');
        h.add.mockResolvedValue({ success: true });
        h.showError.mock.calls[0][1].onRetry();
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('AAPL añadido a la watchlist'));
    });

    it('excepcion: showErrorToast y se puede volver a intentar', async () => {
        h.add.mockRejectedValue(new Error('net'));
        const d = open();
        fireEvent.click(d.getByText('pick-aapl'));
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(d.getByLabelText('q')).not.toBeDisabled();
    });

    it('mientras anade: estado Anadiendo y buscador desactivado', async () => {
        let resolve!: (v: unknown) => void;
        h.add.mockReturnValue(new Promise((r) => { resolve = r; }));
        const d = open();
        fireEvent.click(d.getByText('pick-aapl'));
        expect(await d.findByText('Añadiendo AAPL…')).toBeInTheDocument();
        expect(d.getByLabelText('q')).toBeDisabled();
        fireEvent.click(d.getByText('pick-san'));
        expect(h.add).toHaveBeenCalledTimes(1);
        resolve({ success: false });
        await waitFor(() => expect(d.queryByText('Añadiendo AAPL…')).not.toBeInTheDocument());
    });
});

describe('WatchlistAddButton alta manual por simbolo', () => {
    it('texto con forma de ticker ofrece anadir en mayusculas y lo guarda sin nombre', async () => {
        h.add.mockResolvedValue({ success: true });
        const d = open();
        type(d, ' kkr ');
        fireEvent.click(d.getByRole('button', { name: 'Añadir «KKR» por su símbolo' }));
        await waitFor(() => expect(h.add).toHaveBeenCalledWith('KKR', undefined));
    });

    it.each([['', 0], ['   ', 0], ['no es ticker!', 0], ['a'.repeat(40), 0]])('%j no ofrece alta manual', (value) => {
        const d = open();
        type(d, value as string);
        expect(d.queryByRole('button', { name: /por su símbolo/ })).not.toBeInTheDocument();
    });

    it('un ticker ya seguido no ofrece alta manual y dice que ya se sigue', () => {
        const d = open(['KKR']);
        type(d, 'kkr');
        expect(d.queryByRole('button', { name: /por su símbolo/ })).not.toBeInTheDocument();
        expect(d.getByText(/Ya sigues «KKR»/)).toBeInTheDocument();
    });
});
