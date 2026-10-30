import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/portfolio.actions', () => ({ addTransaction: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
vi.mock('@/components/ui/dialog', () => ({
    DialogContent: ({ children }: { children: React.ReactNode }) => <div role="dialog">{children}</div>,
    DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
    DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}));
vi.mock('@/components/search/TickerSearchInput', () => ({
    TickerSearchInput: ({ onSelect }: { onSelect: (s: { symbol: string; name: string }) => void }) => (
        <>
            <button type="button" onClick={() => onSelect({ symbol: 'VOLV-B.ST', name: 'Volvo' })}>pick-volvo</button>
            <button type="button" onClick={() => onSelect({ symbol: 'NOVO-B.CO', name: 'Novo Nordisk' })}>pick-novo</button>
        </>
    ),
}));
import AddTransactionDialog from '@/components/portfolio/AddTransactionDialog';

describe('Nueva inversion: divisa por defecto de bolsas nordicas', () => {
    it('Volvo (.ST) propone SEK, no EUR', () => {
        render(<AddTransactionDialog userId="u" onClose={() => {}} />);
        fireEvent.click(screen.getByText('pick-volvo'));
        expect(screen.getByLabelText('Moneda de la operación').textContent).toContain('SEK');
        expect(screen.getByText(/Precio \(SEK\)/)).toBeInTheDocument();
    });

    it('Novo Nordisk (.CO) propone DKK', () => {
        render(<AddTransactionDialog userId="u" onClose={() => {}} />);
        fireEvent.click(screen.getByText('pick-novo'));
        expect(screen.getByText(/Precio \(DKK\)/)).toBeInTheDocument();
    });
});
