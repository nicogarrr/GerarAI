import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getDcaBacktest } = vi.hoisted(() => ({ getDcaBacktest: vi.fn() }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaBacktest }));
vi.mock('@/components/watchlist/DcaHitRatesCard', () => ({ default: () => null }));

import DcaBacktestPanel from '@/components/proPicks/DcaBacktestPanel';

describe('DcaBacktestPanel aportación base', () => {
    beforeEach(() => getDcaBacktest.mockReset().mockResolvedValue({ data: null, error: null }));

    it('acepta la coma es-ES y envía el número correcto', async () => {
        render(<DcaBacktestPanel />);
        const input = screen.getByLabelText(/aportación base/i);
        fireEvent.change(input, { target: { value: '50,5' } });
        fireEvent.submit(screen.getByRole('button', { name: /ejecutar/i }).closest('form')!);
        await waitFor(() => expect(getDcaBacktest).toHaveBeenCalledTimes(1));
        expect(getDcaBacktest.mock.calls[0][0].base).toBe(50.5);
    });

    it('entrada inválida: aviso visible y NUNCA reinterpreta a 100 en silencio', async () => {
        render(<DcaBacktestPanel />);
        const input = screen.getByLabelText(/aportación base/i);
        fireEvent.change(input, { target: { value: 'abc' } });
        fireEvent.submit(screen.getByRole('button', { name: /ejecutar/i }).closest('form')!);
        expect(await screen.findByRole('alert')).toHaveTextContent('Introduce una aportación base mayor que 0.');
        expect(getDcaBacktest).not.toHaveBeenCalled();
    });

    it('cero o negativo: aviso visible y no ejecuta', async () => {
        render(<DcaBacktestPanel />);
        const input = screen.getByLabelText(/aportación base/i);
        fireEvent.change(input, { target: { value: '-50' } });
        fireEvent.submit(screen.getByRole('button', { name: /ejecutar/i }).closest('form')!);
        expect(await screen.findByRole('alert')).toHaveTextContent('Introduce una aportación base mayor que 0.');
        expect(getDcaBacktest).not.toHaveBeenCalled();
    });

    it('formato ambiguo: explica la gramática esperada y no ejecuta', async () => {
        render(<DcaBacktestPanel />);
        const input = screen.getByLabelText(/aportación base/i);
        fireEvent.change(input, { target: { value: '1,234' } });
        fireEvent.submit(screen.getByRole('button', { name: /ejecutar/i }).closest('form')!);
        expect(await screen.findByRole('alert')).toHaveTextContent(/Formato de número ambiguo/);
        expect(getDcaBacktest).not.toHaveBeenCalled();
    });

    it('corregir el valor limpia el aviso y ejecuta', async () => {
        render(<DcaBacktestPanel />);
        const input = screen.getByLabelText(/aportación base/i);
        fireEvent.change(input, { target: { value: 'abc' } });
        fireEvent.submit(screen.getByRole('button', { name: /ejecutar/i }).closest('form')!);
        expect(await screen.findByRole('alert')).toBeInTheDocument();
        fireEvent.change(input, { target: { value: '250' } });
        fireEvent.submit(screen.getByRole('button', { name: /ejecutar/i }).closest('form')!);
        await waitFor(() => expect(getDcaBacktest).toHaveBeenCalledTimes(1));
        expect(getDcaBacktest.mock.calls[0][0].base).toBe(250);
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
});
