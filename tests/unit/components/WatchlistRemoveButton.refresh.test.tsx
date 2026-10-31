import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const { remove, refresh, success, showError } = vi.hoisted(() => ({ remove: vi.fn(), refresh: vi.fn(), success: vi.fn(), showError: vi.fn() }));
vi.mock('@/lib/actions/watchlist.actions', () => ({ removeFromWatchlist: remove }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
vi.mock('sonner', () => ({ toast: { success } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: showError }));
import WatchlistRemoveButton from '@/components/watchlist/WatchlistRemoveButton';
import { WatchlistMembership, WatchlistEntry, WatchlistCount } from '@/components/watchlist/WatchlistMembership';

// El paginador separa «Página x de y» en su propio span (NBSP/huérfanos 390px):
// hay que casar por textContent normalizado, no por texto plano.
const byTextContent = (text: string) => (_: string, el?: Element | null) =>
    (el?.textContent ?? '').replace(/\s+/g, ' ').trim() === text;
function View() {
    return <WatchlistMembership><WatchlistCount symbols={['AAPL', 'MSFT']} page={1} totalPages={1} /><WatchlistEntry as="article" symbol="AAPL"><span>AAPL card</span><WatchlistRemoveButton symbol="AAPL" /></WatchlistEntry><table><tbody><WatchlistEntry as="tr" symbol="AAPL"><td>AAPL row</td></WatchlistEntry></tbody></table><WatchlistEntry as="article" symbol="MSFT"><span>MSFT card</span></WatchlistEntry></WatchlistMembership>;
}
describe('Confirmed watchlist removal while server refresh is pending', () => {
    beforeEach(() => vi.clearAllMocks());
    it('hides mobile card and desktop row and updates count immediately after success', async () => {
        remove.mockResolvedValue({ success: true });
        render(<View />);
        fireEvent.click(screen.getByRole('button', { name: 'Quitar AAPL de la watchlist' }));
        await waitFor(() => expect(success).toHaveBeenCalled());
        expect(screen.queryByText('AAPL card')).not.toBeInTheDocument();
        expect(screen.queryByText('AAPL row')).not.toBeInTheDocument();
        expect(screen.getByText('MSFT card')).toBeInTheDocument();
        expect(screen.getByText(byTextContent('1 empresa · Página 1 de 1'))).toBeInTheDocument();
        expect(refresh).toHaveBeenCalledOnce();
    });
    it('keeps membership and count unchanged on failure', async () => {
        remove.mockResolvedValue({ success: false, message: 'Error' });
        render(<View />);
        fireEvent.click(screen.getByRole('button', { name: 'Quitar AAPL de la watchlist' }));
        await waitFor(() => expect(showError).toHaveBeenCalled());
        expect(screen.getByText('AAPL card')).toBeInTheDocument();
        expect(screen.getByText(byTextContent('2 empresas · Página 1 de 1'))).toBeInTheDocument();
        expect(refresh).not.toHaveBeenCalled();
    });
    it('a thrown request keeps the entry and can retry successfully', async () => {
        const error = new Error('Offline');
        remove.mockRejectedValueOnce(error).mockResolvedValueOnce({ success: true });
        render(<View />);
        fireEvent.click(screen.getByRole('button', { name: 'Quitar AAPL de la watchlist' }));
        await waitFor(() => expect(showError).toHaveBeenCalledWith(error, { onRetry: expect.any(Function) }));
        expect(screen.getByText('AAPL card')).toBeInTheDocument();
        expect(screen.getByRole('button')).toBeEnabled();
        expect(refresh).not.toHaveBeenCalled();
        await act(async () => { await showError.mock.calls[0][1].onRetry(); });
        expect(remove).toHaveBeenCalledTimes(2);
        expect(screen.queryByText('AAPL card')).not.toBeInTheDocument();
        expect(screen.queryByText('AAPL row')).not.toBeInTheDocument();
        expect(screen.getByText(byTextContent('1 empresa · Página 1 de 1'))).toBeInTheDocument();
        expect(refresh).toHaveBeenCalledOnce();
    });
    it('an unsuccessful response exposes retry and never flashes a success', async () => {
        remove.mockResolvedValueOnce({ success: false }).mockResolvedValueOnce({ success: true });
        render(<View />);
        fireEvent.click(screen.getByRole('button', { name: 'Quitar AAPL de la watchlist' }));
        await waitFor(() => expect(showError).toHaveBeenCalledWith('No se pudo eliminar de la watchlist', { onRetry: expect.any(Function) }));
        expect(success).not.toHaveBeenCalled();
        expect(screen.getByText(byTextContent('2 empresas · Página 1 de 1'))).toBeInTheDocument();
        await act(async () => { await showError.mock.calls[0][1].onRetry(); });
        expect(success).toHaveBeenCalledWith('AAPL eliminado de la watchlist');
        expect(screen.getByText(byTextContent('1 empresa · Página 1 de 1'))).toBeInTheDocument();
    });
    it('does not remove before the server confirms the DELETE', async () => {
        let resolve!: (value: { success: boolean }) => void;
        remove.mockReturnValue(new Promise((done) => { resolve = done; }));
        render(<View />);
        fireEvent.click(screen.getByRole('button', { name: 'Quitar AAPL de la watchlist' }));
        expect(screen.getByText('AAPL card')).toBeInTheDocument();
        expect(screen.getByRole('button')).toBeDisabled();
        await act(async () => resolve({ success: true }));
        expect(screen.queryByText('AAPL card')).not.toBeInTheDocument();
    });
});
