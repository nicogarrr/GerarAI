import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const get = vi.fn();
vi.mock('@/lib/actions/home-attention.actions', () => ({ getHomeAttention: () => get() }));
import HomeAttention from '@/components/HomeAttention';
const empty = { thesis: { unavailable: false, items: [] }, dca: { unavailable: false, items: [] } };
beforeEach(() => { get.mockReset(); });
describe('HomeAttention', () => {
    it('honest empty, no invented signals', async () => {
        get.mockResolvedValue(empty); render(<HomeAttention />);
        expect(await screen.findByText(/Sin cambios de tesis pendientes/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /Lista completa/ })).toHaveAttribute('href', '/watchlist');
    });
    it('shows thesis and DCA as separate facts with direct destinations', async () => {
        get.mockResolvedValue({ thesis: { unavailable: false, items: [{ id: 17, symbol: 'ASTS', summary: 'Contrato nuevo', direction: 'negative', createdAt: '2026-10-28' }] }, dca: { unavailable: false, items: [{ id: 'dca-UBER', symbol: 'UBER', level: 4, threshold: 3, signalDate: '2026-10-27', forming: true }] } });
        render(<HomeAttention />);
        expect(await screen.findByText('Deterioro de tesis')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /Revisar cambio de ASTS/ })).toHaveAttribute('href', '/research/ASTS?view=changes#thesis-change-17');
        expect(screen.getByText('Nivel DCA 4X')).toBeInTheDocument();
        expect(screen.getByText(/Mes en formación/)).toBeInTheDocument();
    });
    it('partial failure remains visible and can retry', async () => {
        get.mockResolvedValueOnce({ ...empty, thesis: { unavailable: true, items: [] } }).mockResolvedValue(empty);
        render(<HomeAttention />); fireEvent.click(await screen.findByRole('button', { name: 'Reintentar' }));
        await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
        expect(await screen.findByText(/Sin cambios de tesis pendientes/)).toBeInTheDocument();
    });
    it('rejects total failure as empty and recovers', async () => {
        get.mockRejectedValue(new Error('offline')); render(<HomeAttention />);
        expect(await screen.findByText(/los cambios de tesis ni los niveles DCA/)).toBeInTheDocument();
        expect(screen.queryByText(/^Sin cambios de tesis pendientes/)).not.toBeInTheDocument();
    });
    it('paginates with no hidden remainder', async () => {
        get.mockResolvedValue({ ...empty, thesis: { unavailable: false, items: Array.from({length: 7}, (_,i) => ({ id:i, symbol:`TEST${i}`, summary:`Cambio ${i}`, direction:'neutral', createdAt:'2026-10-28' })) } });
        render(<HomeAttention />); await screen.findByText('TEST0');
        expect(screen.queryByText('TEST6')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name:'Siguiente' }));
        expect(screen.getByText('TEST6')).toBeInTheDocument();
        expect(screen.getByText('2 / 2 · 7 elementos')).toBeInTheDocument();
    });
});
